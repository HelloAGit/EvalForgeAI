"""Persist evaluation runs/results as metric observations and change events."""
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    EvaluationResult, EvaluationRun, MetricAggregate, MetricObservation, utcnow,
)
from app.services.events import emit_event
from app.services.metrics_catalog import CATALOG_BY_KEY, resolve_catalog_key
from app.services.stats_utils import describe_from_sums

RESULT_STATUSES = {"PASSED", "FAILED", "ERROR", "COMPLETED"}
FAILING_STATUSES = ("FAILED", "ERROR")
TERMINAL_RUN_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


def normalise_status(status: Optional[str], error_type: Optional[str]) -> str:
    if error_type:
        return "ERROR"
    s = (status or "").upper()
    return s if s in RESULT_STATUSES else "COMPLETED"


def _resolve_unique(metrics: Dict[str, float]) -> Dict[str, Optional[str]]:
    """raw metric name -> catalogue key. Only one raw name per catalogue key per
    result is counted (first by alias priority, then name) to avoid double counting."""
    resolved: Dict[str, Optional[str]] = {}
    taken: Dict[str, tuple] = {}
    for name in sorted(metrics):
        key = resolve_catalog_key(name)
        resolved[name] = None
        if key is None:
            continue
        m = CATALOG_BY_KEY[key]
        lname = name.lower()
        prio = m.aliases.index(lname) if lname in m.aliases else (-1 if lname == key else len(m.aliases))
        if key not in taken or prio < taken[key][0]:
            if key in taken:
                resolved[taken[key][1]] = None
            taken[key] = (prio, name)
            resolved[name] = key
    return resolved


def create_run(db: Session, *, project_id: str, model_id: str, provider: Optional[str] = None,
               suite: Optional[str] = None, dataset_id: Optional[str] = None,
               dataset_version: Optional[str] = None, category: Optional[str] = None,
               trigger: str = "manual", schedule_job_id: Optional[str] = None,
               idempotency_key: Optional[str] = None, status: str = "RUNNING",
               config: Optional[dict] = None) -> EvaluationRun:
    run = EvaluationRun(project_id=project_id, model_name=model_id, model_id=model_id, provider=provider,
                        suite=suite, dataset_id=dataset_id, dataset_version=dataset_version,
                        category=category, trigger=trigger, schedule_job_id=schedule_job_id,
                        idempotency_key=idempotency_key, status=status, config=config,
                        started_at=utcnow() if status == "RUNNING" else None)
    db.add(run)
    db.flush()
    emit_event(db, "run.created", project_id, run.id,
               {"status": run.status, "model_id": model_id, "category": category, "trigger": trigger})
    return run


def add_results(db: Session, run: EvaluationRun, results: Iterable[Dict[str, Any]]) -> int:
    """Add result rows + one observation per numeric metric. Emits a single event for the batch."""
    count = 0
    touched_keys = set()
    for r in results:
        metrics = {k: float(v) for k, v in (r.get("metrics") or {}).items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)}
        status = normalise_status(r.get("status"), r.get("error_type"))
        result = EvaluationResult(
            evaluation_run_id=run.id, sample_id=str(r["sample_id"]), prompt=r.get("prompt", ""),
            expected_output=r.get("expected_output"), actual_output=r.get("actual_output"),
            latency_ms=r.get("latency_ms"), token_count=r.get("token_count"), metrics=metrics,
            mubit_request_id=r.get("mubit_request_id"), status=status, error_type=r.get("error_type"),
            cost_usd=r.get("cost_usd"), evidence=r.get("evidence"),
        )
        db.add(result)
        db.flush()
        resolved = _resolve_unique(metrics)
        for name, value in metrics.items():
            key = resolved.get(name)
            if key:
                touched_keys.add(key)
            db.add(MetricObservation(
                run_id=run.id, result_id=result.id, sample_id=result.sample_id, metric_key=name,
                catalog_key=key, value=value,
                method=(CATALOG_BY_KEY[key].method if key else None),
                method_version=(CATALOG_BY_KEY[key].method_version if key else None)))
        count += 1
    if count:
        db.flush()
        refresh_aggregates(db, run.id, touched_keys)
        emit_event(db, "results.added", run.project_id, run.id, {"count": count, "model_id": run.model_id})
    return count


def refresh_aggregates(db: Session, run_id: str, keys: Optional[Iterable[str]] = None) -> None:
    q = select(MetricObservation.catalog_key, func.count(), func.sum(MetricObservation.value),
               func.sum(MetricObservation.value * MetricObservation.value)).where(
        MetricObservation.run_id == run_id, MetricObservation.catalog_key.is_not(None))
    if keys:
        q = q.where(MetricObservation.catalog_key.in_(list(keys)))
    q = q.group_by(MetricObservation.catalog_key)
    for key, n, total, total_sq in db.execute(q).all():
        d = describe_from_sums(int(n), float(total), float(total_sq))
        agg = db.scalar(select(MetricAggregate).where(MetricAggregate.run_id == run_id,
                                                      MetricAggregate.catalog_key == key))
        if agg is None:
            agg = MetricAggregate(run_id=run_id, catalog_key=key, n=0, mean=0.0)
            db.add(agg)
        agg.n, agg.mean, agg.std = d["n"], d["mean"], d["std"]
        agg.ci_low, agg.ci_high, agg.updated_at = d["ci_low"], d["ci_high"], utcnow()


def complete_run(db: Session, run: EvaluationRun, status: str = "COMPLETED",
                 error_message: Optional[str] = None) -> EvaluationRun:
    if run.status in TERMINAL_RUN_STATUSES:
        return run
    run.status = status
    run.completed_at = utcnow()
    run.error_message = error_message
    db.flush()
    from app.services.dashboard import quality_index_for_run
    qi = quality_index_for_run(db, run.id)
    run.quality_index = qi
    emit_event(db, "run.completed" if status == "COMPLETED" else f"run.{status.lower()}",
               run.project_id, run.id, {"status": status, "quality_index": qi, "model_id": run.model_id})
    return run

"""Canonical, immutable report snapshot shared by PDF and video generation.

The payload is assembled only from persisted evaluation data via the same aggregation code the
dashboard uses, so report figures always match dashboard/database figures. It is hashed
(canonical JSON, SHA-256) and stored write-once in ``report_snapshots``.
"""
import hashlib
import json
import math
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.entities import (
    EvaluationResult, EvaluationRun, MetricObservation, Project, ReportSnapshot, StatisticalResult, utcnow,
)
from app.services import dashboard as dash
from app.services.metrics_catalog import CATALOG, CATALOG_BY_KEY, CATALOG_VERSION, observation_metrics
from app.services.stats_utils import compare_samples

SNAPSHOT_SCHEMA_VERSION = "1.0"
CHART_IDS = ["quality_trend", "model_ranking", "llm_performance", "rag_quality", "agent_outcomes",
             "failure_classification", "latency_percentiles", "distributions", "confidence_intervals",
             "regression", "usage"]
SMALL_SAMPLE = 30


class SnapshotError(ValueError):
    pass


def _clean(o: Any) -> Any:
    """Make JSON-safe (NaN/inf -> None, datetimes -> ISO)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, datetime):
        return o.isoformat() + "Z"
    return o


def canonical_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _status_band(qi: Optional[float]) -> Dict[str, Any]:
    if qi is None:
        return {"label": "Not determinable", "rule": "Quality index is N/A for this scope."}
    label = "Good" if qi >= 80 else "Needs attention" if qi >= 60 else "Critical"
    return {"label": label, "rule": "Quality index >= 80 Good; 60-80 Needs attention; < 60 Critical (presentation bands only)."}


def _scope_filters(db: Session, project_id: str, cfg: Dict[str, Any]) -> dash.Filters:
    return dash.Filters(project_id=project_id,
                        run_ids=tuple(cfg["run_ids"]) if cfg.get("run_ids") else None,
                        model_ids=tuple(cfg["model_ids"]) if cfg.get("model_ids") else None,
                        date_from=dash.parse_date(cfg.get("date_from")),
                        date_to=dash.parse_date(cfg.get("date_to"), end_of_day=True))


def _values(db: Session, f: dash.Filters, key: str) -> List[float]:
    return [float(v) for v in db.scalars(dash._obs_select(f, MetricObservation.value)
                                         .where(MetricObservation.catalog_key == key).limit(dash.MAX_ROWS))]


def _statistical_results(db: Session, f: dash.Filters, models: List[str], runs: List[dict], metric_keys: List[str]) -> List[dict]:
    out: List[dict] = []
    n = 0

    def add(metric: str, base_label: str, cand_label: str, fb: dash.Filters, fc: dash.Filters):
        nonlocal n
        res = compare_samples(_values(db, fb, metric), _values(db, fc, metric))
        n += 1
        out.append({"id": f"stat-{n}", "metric_key": metric, "metric_name": CATALOG_BY_KEY[metric].name,
                    "baseline": base_label, "candidate": cand_label, **res})

    for key in metric_keys:
        if len(models) >= 2:
            base = models[0]
            for cand in models[1:]:
                add(key, f"model:{base}", f"model:{cand}", _replace(f, model_ids=None, model_id=base), _replace(f, model_ids=None, model_id=cand))
        elif len(runs) >= 2:
            add(key, f"run:{runs[0]['id']}", f"run:{runs[-1]['id']}",
                _replace(f, run_ids=None, run_id=runs[0]["id"]), _replace(f, run_ids=None, run_id=runs[-1]["id"]))
    return out


def _replace(f: dash.Filters, **kw) -> dash.Filters:
    from dataclasses import replace
    return replace(f, **kw)


def build_payload(db: Session, owner_id: str, config: Dict[str, Any], snapshot_id: str) -> Dict[str, Any]:
    project = db.get(Project, config.get("project_id"))
    if project is None:
        raise SnapshotError("Project not found")
    f = _scope_filters(db, project.id, config)

    run_rows = db.scalars(dash._run_select(f, EvaluationRun).order_by(EvaluationRun.created_at)).all()
    if not run_rows:
        raise SnapshotError("No evaluation runs match the selected scope.")
    n_results = db.scalar(dash._result_select(f, func.count())) or 0
    n_obs = db.scalar(dash._obs_select(f, func.count())) or 0
    if n_results == 0 and n_obs == 0:
        raise SnapshotError("The selected runs have no persisted results or metric observations.")

    kpis, ctx = dash.build_kpis(db, f)
    alerts = dash.regression_alerts(db, f)
    charts_all = dash.build_charts(db, f, ctx, alerts)
    trend = dash.trends(db, f, "quality_index", "day")
    charts_all["quality_trend"] = {"series": trend["series"], "unit": "index", "na_reason": trend["na_reason"]}
    wanted_charts = [c for c in (config.get("charts") or CHART_IDS) if c in CHART_IDS]
    wanted_metrics = [m for m in (config.get("metrics") or [m.key for m in observation_metrics()]) if m in CATALOG_BY_KEY]

    runs = [{"id": r.id, "model_id": r.model_id or r.model_name, "provider": r.provider, "suite": r.suite,
             "dataset_version": r.dataset_version, "category": r.category, "status": r.status,
             "created_at": r.created_at, "completed_at": r.completed_at, "quality_index": r.quality_index}
            for r in run_rows]
    models = sorted({r["model_id"] for r in runs if r["model_id"]})
    if config.get("model_ids"):
        models = [m for m in config["model_ids"] if m in models]  # keep caller order: first = baseline

    per_model = dash._per_model_stats(db, f)
    kpi_by_key = {k["key"]: k for k in kpis}
    metrics = []
    for key in wanted_metrics:
        k = dict(kpi_by_key[key])
        k.pop("definition", None)
        k["ci_low"], k["ci_high"] = (k["ci"] or [None, None])
        k.pop("ci", None)
        k["per_model"] = [{"model_id": m, "n": st[key]["n"], "value": st[key]["mean"] if st[key]["n"] >= settings.MIN_OBSERVATIONS else None,
                           "ci_low": st[key]["ci_low"] if st[key]["n"] >= settings.MIN_OBSERVATIONS else None,
                           "ci_high": st[key]["ci_high"] if st[key]["n"] >= settings.MIN_OBSERVATIONS else None}
                          for m, st in sorted(per_model.items()) if key in st]
        metrics.append(k)
    operational = [dict(k) for k in kpis if CATALOG_BY_KEY[k["key"]].kind == "derived"]

    available = [m["key"] for m in metrics if m["status"] == "ok"]
    stat_results = _statistical_results(db, f, models, runs, available)

    failed_rows = db.execute(dash._result_select(f, EvaluationResult.id, EvaluationResult.sample_id, EvaluationResult.evaluation_run_id,
                                                 EvaluationRun.model_id, EvaluationResult.status, EvaluationResult.error_type,
                                                 EvaluationResult.prompt, EvaluationResult.mubit_request_id)
                             .where(EvaluationResult.status.in_(dash.FAILING))
                             .order_by(EvaluationResult.created_at.desc()).limit(50)).all()
    include_cases = bool(config.get("include_cases"))
    failed_cases = [{"result_id": r[0], "sample_id": r[1], "run_id": r[2], "model_id": r[3], "status": r[4],
                     "error_type": r[5], "mubit_request_id": r[7], "evidence_ref": f"result:{r[0]}",
                     **({"prompt_excerpt": (r[6] or "")[:200]} if include_cases else {})} for r in failed_rows]
    failures = {"total_failed": ctx["ops"]["failed"], "total_results": ctx["ops"]["results"],
                "by_classification": charts_all["failure_classification"], "failed_cases": failed_cases,
                "failed_cases_truncated": ctx["ops"]["failed"] > len(failed_cases)}

    limitations: List[str] = []
    na = [m for m in metrics if m["status"] == "na"]
    for m in na:
        limitations.append(f"{m['name']} is N/A: {m['na_reason']}")
    small = [m for m in metrics if m["status"] == "ok" and m["n_observations"] < SMALL_SAMPLE]
    if small:
        limitations.append("Sample sizes below %d for: %s. Confidence intervals assume approximately normal sampling distributions "
                           "and may be unreliable." % (SMALL_SAMPLE, ", ".join(m["name"] for m in small)))
    limitations.append("Observations from different runs are pooled and treated as independent; clustering by prompt/sample is not modelled.")
    if stat_results:
        limitations.append("%d statistical tests were run at alpha=0.05 without multiplicity correction; treat isolated significant results with caution." % len(stat_results))
    if not ctx["ops"]["cost_n"]:
        limitations.append("No evaluation cost was recorded; cost figures are N/A.")
    if ctx["qi"]["value"] is None:
        limitations.append("Overall Quality Index is N/A: %s" % ctx["qi"]["na_reason"])

    recommendations = _recommendations(metrics, alerts, stat_results, failures, ctx)
    metric_defs = [{**CATALOG_BY_KEY[m["key"]].public(), "catalog_version": CATALOG_VERSION} for m in metrics]
    times = db.execute(dash._obs_select(f, func.min(MetricObservation.created_at), func.max(MetricObservation.created_at))).one()
    created = utcnow()
    evidence_index = (["qi"] + [f"metric:{m['key']}" for m in metrics] + [f"run:{r['id']}" for r in runs] +
                      [f"model:{m}" for m in models] + [c["evidence_ref"] for c in failed_cases] +
                      [f"stat:{s['id']}" for s in stat_results] + [f"chart:{c}" for c in wanted_charts] +
                      [f"rec:{r['id']}" for r in recommendations])
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION, "snapshot_id": snapshot_id, "created_at": created,
        "project": {"id": project.id, "name": project.name, "description": project.description},
        "scope": {"run_ids": [r["id"] for r in runs], "model_ids": models, "date_from": config.get("date_from"),
                  "date_to": config.get("date_to"), "include_cases": include_cases, "requested": _requested(config)},
        "runs": runs, "models": models,
        "dataset_versions": sorted({r["dataset_version"] for r in runs if r["dataset_version"]}),
        "evaluation_time_range": {"start": times[0], "end": times[1]},
        "catalog_version": CATALOG_VERSION, "metric_definitions": metric_defs,
        "metrics": metrics, "operational": operational,
        "quality_index": {**ctx["qi"], "band": _status_band(ctx["qi"]["value"])},
        "statistical_results": stat_results,
        "chart_datasets": {c: charts_all[c] for c in wanted_charts},
        "failures": failures, "regressions": alerts, "recommendations": recommendations,
        "limitations": limitations,
        "evidence": {"mubit_request_ids": sorted({c["mubit_request_id"] for c in failed_cases if c["mubit_request_id"]}),
                     "n_results": n_results, "n_observations": n_obs},
        "evidence_index": evidence_index,
        "methodology": {"confidence_level": 0.95, "ci_method": "Student t interval on the mean",
                        "comparison_method": "Welch t-test (unpaired), Cohen's d with pooled SD", "alpha": 0.05,
                        "min_observations": settings.MIN_OBSERVATIONS, "qi_weights": ctx["qi"]["components"]},
    }
    return _clean(payload)


def _requested(config: Dict[str, Any]) -> Dict[str, Any]:
    return {k: config.get(k) for k in ("metrics", "charts", "template") if config.get(k)}


def _recommendations(metrics, alerts, stat_results, failures, ctx) -> List[Dict[str, Any]]:
    """Rule-based recommendations derived from facts in the data (no model-generated advice)."""
    recs: List[Dict[str, Any]] = []

    def add(priority, text, refs):
        recs.append({"id": f"r{len(recs) + 1}", "priority": priority, "text": text, "evidence_refs": refs})
    for a in alerts[:3]:
        add("high" if a["severity"] == "critical" else "medium",
            f"Investigate the regression in {a['name']} for {a['model_id']} between the previous and the latest run "
            f"({'statistically significant' if a['severity'] == 'critical' else 'not statistically confirmed'}).",
            [f"metric:{a['metric_key']}", f"run:{a['latest_run_id']}", f"run:{a['previous_run_id']}"])
    ok = [m for m in metrics if m["status"] == "ok" and m["unit"] == "ratio"]
    def goodness(m):
        return 1 - m["value"] if m["direction"] == "lower_better" else m["value"]
    for m in sorted(ok, key=goodness)[:2]:
        if goodness(m) < 0.8:
            add("medium", f"Prioritise improving {m['name']}, currently the weakest measured quality metric.", [f"metric:{m['key']}"])
    if failures["total_failed"]:
        top = failures["by_classification"][:1]
        add("medium", f"Review the {failures['total_failed']} failed evaluation result(s)"
            + (f"; the most frequent classification is '{top[0]['classification']}'." if top else "."),
            [c["evidence_ref"] for c in failures["failed_cases"][:3]])
    for s in stat_results:
        if s.get("testable") and s.get("significant") and (s.get("mean_difference") or 0) < 0:
            add("high", f"{s['metric_name']} is significantly lower for {s['candidate']} than {s['baseline']}; review before relying on {s['candidate']}.",
                [f"stat:{s['id']}", f"metric:{s['metric_key']}"])
    na = [m for m in metrics if m["status"] == "na" and CATALOG_BY_KEY[m["key"]].qi_weight > 0]
    if na:
        add("low", f"Add evaluators for the {len(na)} quality metric(s) without sufficient observations so the quality index covers more of the system.",
            ["qi"] + [f"metric:{m['key']}" for m in na[:3]])
    return recs[:8]


def create_snapshot(db: Session, owner_id: str, config: Dict[str, Any]) -> ReportSnapshot:
    snapshot_id = str(uuid.uuid4())
    payload = build_payload(db, owner_id, config, snapshot_id)
    snap = ReportSnapshot(id=snapshot_id, owner_id=owner_id, project_id=config["project_id"],
                          schema_version=SNAPSHOT_SCHEMA_VERSION, payload=payload, payload_sha256=canonical_hash(payload))
    db.add(snap)
    db.flush()
    for s in payload["statistical_results"]:
        if s.get("testable"):
            db.add(StatisticalResult(snapshot_id=snapshot_id, project_id=config["project_id"], metric_key=s["metric_key"],
                                     baseline_ref=s["baseline"], candidate_ref=s["candidate"], method=s["method"],
                                     sample_size_baseline=s["n_baseline"], sample_size_candidate=s["n_candidate"],
                                     mean_difference=s["mean_difference"], p_value=s["p_value"], effect_size=s["effect_size"],
                                     ci_low=s["ci_low"], ci_high=s["ci_high"]))
    return snap

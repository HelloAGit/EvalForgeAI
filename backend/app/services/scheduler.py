"""Durable scheduled evaluations.

State lives in the database (``scheduled_jobs``), the worker process calls ``tick`` regularly.
Protections: atomic compare-and-set claim of each slot, one active run per job (no overlap),
per-job daily cap (no runaway usage), unique idempotency keys (no duplicates), no catch-up
storms after downtime, and jobs are created disabled until an administrator enables them.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.entities import Dataset, EvaluationRun, ScheduledJob, utcnow
from app.services import ingest
from app.services.events import emit_event

KINDS = {"daily": timedelta(days=1), "weekly": timedelta(days=7), "dataset_trigger": None, "regression": None}


def create_job(db: Session, *, name: str, kind: str, project_id: str, config: dict,
               max_runs_per_day: Optional[int] = None, created_by: Optional[str] = None,
               first_run_at: Optional[datetime] = None) -> ScheduledJob:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    if not config.get("model_id"):
        raise ValueError("config.model_id is required")
    if kind == "dataset_trigger" and not config.get("dataset_type"):
        raise ValueError("config.dataset_type is required for dataset_trigger jobs")
    if kind in ("daily", "weekly") and not config.get("dataset_id"):
        raise ValueError("config.dataset_id is required for daily/weekly jobs")
    cap = min(max_runs_per_day or 4, settings.SCHEDULER_MAX_RUNS_PER_DAY)
    now = utcnow()
    job = ScheduledJob(name=name, kind=kind, project_id=project_id, config=config, enabled=False,
                       max_runs_per_day=cap, created_by=created_by, last_dataset_seen_at=now,
                       next_run_at=(first_run_at or now + KINDS[kind]) if KINDS[kind] else None)
    db.add(job)
    db.flush()
    return job


def _guard(db: Session, job: ScheduledJob, now: datetime) -> Optional[str]:
    active = db.scalar(select(func.count()).select_from(EvaluationRun).where(
        EvaluationRun.schedule_job_id == job.id, EvaluationRun.status.in_(("PENDING", "RUNNING"))))
    if active:
        return "previous run still active (overlap protection)"
    today = db.scalar(select(func.count()).select_from(EvaluationRun).where(
        EvaluationRun.schedule_job_id == job.id, EvaluationRun.created_at >= now - timedelta(days=1)))
    if today >= min(job.max_runs_per_day, settings.SCHEDULER_MAX_RUNS_PER_DAY):
        return "daily run cap reached (runaway protection)"
    return None


def _queue_run(db: Session, job: ScheduledJob, key: str, trigger: str, now: datetime,
               dataset: Optional[Dataset] = None) -> Optional[EvaluationRun]:
    cfg = job.config
    ds_id = dataset.id if dataset else cfg.get("dataset_id")
    ds = dataset or (db.get(Dataset, ds_id) if ds_id else None)
    if db.scalar(select(func.count()).select_from(EvaluationRun).where(EvaluationRun.idempotency_key == key)):
        job.last_skip_reason = "duplicate slot (idempotency protection)"
        return None
    try:
        with db.begin_nested():
            run = ingest.create_run(
                db, project_id=job.project_id, model_id=cfg["model_id"], provider=cfg.get("provider"),
                suite=cfg.get("suite") or job.name, dataset_id=ds_id, dataset_version=ds.version if ds else None,
                category=ds.type if ds else cfg.get("dataset_type"), trigger=trigger, schedule_job_id=job.id,
                idempotency_key=key, status="PENDING", config={"max_samples": cfg.get("max_samples", 100)})
    except IntegrityError:
        job.last_skip_reason = "duplicate slot (idempotency protection)"
        return None
    job.last_run_at, job.last_status, job.last_skip_reason = now, "QUEUED", None
    return run


def tick(db: Session, now: Optional[datetime] = None) -> List[str]:
    """Queue due runs; returns the ids of queued runs."""
    now = now or utcnow()
    queued: List[str] = []
    for job in db.scalars(select(ScheduledJob).where(ScheduledJob.enabled.is_(True))).all():
        if job.kind in ("daily", "weekly"):
            if job.next_run_at is None or job.next_run_at > now:
                continue
            slot, step = job.next_run_at, KINDS[job.kind]
            nxt = slot + step
            while nxt <= now:  # skip missed slots instead of replaying a backlog
                nxt += step
            claimed = db.execute(update(ScheduledJob).where(ScheduledJob.id == job.id, ScheduledJob.next_run_at == slot,
                                                            ScheduledJob.enabled.is_(True))
                                 .values(next_run_at=nxt)).rowcount
            if claimed != 1:
                continue
            db.refresh(job)
            reason = _guard(db, job, now)
            if reason:
                job.last_skip_reason, job.last_status = reason, "SKIPPED"
                continue
            run = _queue_run(db, job, f"sched:{job.id}:{slot.isoformat()}", "scheduled", now)
            if run:
                queued.append(run.id)
        elif job.kind == "dataset_trigger":
            since = job.last_dataset_seen_at or job.created_at
            q = select(Dataset).where(Dataset.type == job.config["dataset_type"], Dataset.created_at > since)
            if job.config.get("dataset_name"):
                q = q.where(Dataset.name == job.config["dataset_name"])
            fresh = db.scalars(q.order_by(Dataset.created_at)).all()
            if not fresh:
                continue
            newest = fresh[-1]
            job.last_dataset_seen_at = newest.created_at  # one run for the newest dataset, not one per upload
            reason = _guard(db, job, now)
            if reason:
                job.last_skip_reason, job.last_status = reason, "SKIPPED"
                continue
            run = _queue_run(db, job, f"sched:{job.id}:dataset:{newest.id}", "dataset", now, dataset=newest)
            if run:
                queued.append(run.id)
    db.commit()
    return queued


def trigger_release(db: Session, job: ScheduledJob, release_tag: str, now: Optional[datetime] = None) -> Optional[EvaluationRun]:
    """Regression run for a new model/prompt release. Idempotent per release tag."""
    if job.kind != "regression":
        raise ValueError("Only regression jobs can be triggered by a release")
    if not job.enabled:
        raise PermissionError("Job is disabled")
    now = now or utcnow()
    reason = _guard(db, job, now)
    if reason:
        job.last_skip_reason, job.last_status = reason, "SKIPPED"
        db.commit()
        raise RuntimeError(reason)
    run = _queue_run(db, job, f"sched:{job.id}:release:{release_tag}", "release", now)
    db.commit()
    return run

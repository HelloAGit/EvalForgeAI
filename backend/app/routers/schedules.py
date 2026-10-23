from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.entities import Project, ScheduledJob
from app.security import User, get_current_user, require_admin
from app.services import scheduler as sched

router = APIRouter(prefix="/api/v1/schedules", tags=["Scheduled evaluations"])


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(pattern="^(daily|weekly|dataset_trigger|regression)$")
    project_id: str
    config: Dict[str, Any]
    max_runs_per_day: Optional[int] = Field(None, ge=1, le=1000)
    first_run_at: Optional[datetime] = None


class ReleaseIn(BaseModel):
    release_tag: str = Field(min_length=1, max_length=200)


def _d(j: ScheduledJob) -> dict:
    iso = lambda x: x.isoformat() + "Z" if x else None
    return {"id": j.id, "name": j.name, "kind": j.kind, "enabled": j.enabled, "project_id": j.project_id,
            "config": j.config, "next_run_at": iso(j.next_run_at), "last_run_at": iso(j.last_run_at),
            "last_status": j.last_status, "last_skip_reason": j.last_skip_reason, "max_runs_per_day": j.max_runs_per_day}


def _get(db: Session, job_id: str) -> ScheduledJob:
    j = db.get(ScheduledJob, job_id)
    if j is None:
        raise HTTPException(404, "Schedule not found")
    return j


@router.get("")
def list_schedules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [_d(j) for j in db.query(ScheduledJob).order_by(ScheduledJob.created_at.desc()).limit(200)]


@router.post("", status_code=201)
def create_schedule(body: ScheduleIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if db.get(Project, body.project_id) is None:
        raise HTTPException(404, "Project not found")
    try:
        job = sched.create_job(db, name=body.name, kind=body.kind, project_id=body.project_id, config=body.config,
                               max_runs_per_day=body.max_runs_per_day, created_by=user.id, first_run_at=body.first_run_at)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    db.commit()
    return _d(job)


@router.post("/{job_id}/enable")
def enable(job_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    j = _get(db, job_id)
    j.enabled = True
    db.commit()
    return _d(j)


@router.post("/{job_id}/disable")
def disable(job_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    j = _get(db, job_id)
    j.enabled = False
    db.commit()
    return _d(j)


@router.post("/{job_id}/trigger", status_code=202)
def trigger_release(job_id: str, body: ReleaseIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Queue a regression run for a new model/prompt release (idempotent per release_tag)."""
    j = _get(db, job_id)
    try:
        run = sched.trigger_release(db, j, body.release_tag)
    except PermissionError as exc:
        raise HTTPException(409, str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc))
    return {"queued": run is not None, "run_id": run.id if run else None, "schedule": _d(j)}

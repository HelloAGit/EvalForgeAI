"""Ingestion API: projects, datasets and evaluation runs/results (writes feed the live dashboard)."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.entities import Dataset, EvaluationRun, Project
from app.security import User, get_current_user, require_admin
from app.services import ingest
from app.services.events import emit_event

router = APIRouter(prefix="/api/v1", tags=["Evaluations"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)


class DatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str = Field(pattern="^(llm|rag|agent)$")
    version: str = Field("v1", max_length=64)
    content: List[Dict[str, Any]] = Field(max_length=100000)


class ResultIn(BaseModel):
    sample_id: str = Field(min_length=1, max_length=200)
    prompt: str = ""
    expected_output: Optional[str] = None
    actual_output: Optional[str] = None
    latency_ms: Optional[float] = Field(None, ge=0)
    token_count: Optional[int] = Field(None, ge=0)
    cost_usd: Optional[float] = Field(None, ge=0)
    metrics: Dict[str, float] = Field(default_factory=dict)
    status: Optional[str] = Field(None, pattern="^(PASSED|FAILED|ERROR|COMPLETED)$")
    error_type: Optional[str] = Field(None, max_length=100)
    mubit_request_id: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None


class RunIn(BaseModel):
    project_id: str
    model_id: str = Field(min_length=1, max_length=200)
    provider: Optional[str] = Field(None, max_length=100)
    suite: Optional[str] = Field(None, max_length=200)
    dataset_id: Optional[str] = None
    dataset_version: Optional[str] = Field(None, max_length=64)
    category: Optional[str] = Field(None, pattern="^(llm|rag|agent)$")
    results: List[ResultIn] = Field(default_factory=list, max_length=5000)
    complete: bool = False


class ResultsIn(BaseModel):
    results: List[ResultIn] = Field(min_length=1, max_length=5000)
    complete: bool = False


def _run_dict(r: EvaluationRun) -> dict:
    return {"id": r.id, "project_id": r.project_id, "model_id": r.model_id or r.model_name, "provider": r.provider,
            "suite": r.suite, "dataset_version": r.dataset_version, "category": r.category, "status": r.status,
            "trigger": r.trigger, "quality_index": r.quality_index, "created_at": r.created_at.isoformat() + "Z",
            "completed_at": r.completed_at.isoformat() + "Z" if r.completed_at else None, "error_message": r.error_message}


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = Project(name=body.name, description=body.description)
    db.add(p)
    db.flush()
    emit_event(db, "project.created", p.id, None, {"name": p.name})
    db.commit()
    return {"id": p.id, "name": p.name, "description": p.description, "created_at": p.created_at.isoformat() + "Z"}


@router.get("/projects")
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [{"id": p.id, "name": p.name, "description": p.description} for p in db.query(Project).order_by(Project.name).limit(500)]


@router.post("/datasets", status_code=201)
def create_dataset(body: DatasetIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    d = Dataset(name=body.name, type=body.type, version=body.version, content=body.content)
    db.add(d)
    db.flush()
    emit_event(db, "dataset.created", None, None, {"dataset_id": d.id, "type": d.type, "version": d.version})
    db.commit()
    return {"id": d.id, "name": d.name, "type": d.type, "version": d.version, "size": len(body.content)}


@router.get("/datasets")
def list_datasets(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [{"id": d.id, "name": d.name, "type": d.type, "version": d.version, "size": len(d.content or [])}
            for d in db.query(Dataset).order_by(Dataset.created_at.desc()).limit(200)]


@router.post("/evaluations/runs", status_code=201)
def create_run(body: RunIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if db.get(Project, body.project_id) is None:
        raise HTTPException(404, "Project not found")
    run = ingest.create_run(db, project_id=body.project_id, model_id=body.model_id, provider=body.provider,
                            suite=body.suite, dataset_id=body.dataset_id, dataset_version=body.dataset_version,
                            category=body.category, trigger="manual")
    ingest.add_results(db, run, [r.model_dump() for r in body.results])
    if body.complete:
        ingest.complete_run(db, run)
    db.commit()
    return _run_dict(run)


def _get_open_run(db: Session, run_id: str) -> EvaluationRun:
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/evaluations/runs/{run_id}/results", status_code=201)
def add_results(run_id: str, body: ResultsIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = _get_open_run(db, run_id)
    if run.status in ingest.TERMINAL_RUN_STATUSES:
        raise HTTPException(409, f"Run is {run.status}; results can no longer be added")
    if run.status == "PENDING":
        run.status = "RUNNING"
    n = ingest.add_results(db, run, [r.model_dump() for r in body.results])
    if body.complete:
        ingest.complete_run(db, run)
    db.commit()
    return {**_run_dict(run), "added": n}


@router.post("/evaluations/runs/{run_id}/complete")
def complete_run(run_id: str, failed: bool = False, error_message: Optional[str] = None,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = _get_open_run(db, run_id)
    ingest.complete_run(db, run, "FAILED" if failed else "COMPLETED", error_message)
    db.commit()
    return _run_dict(run)


@router.get("/evaluations/runs")
def list_runs(project_id: Optional[str] = None, limit: int = 50, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    q = db.query(EvaluationRun)
    if project_id:
        q = q.filter(EvaluationRun.project_id == project_id)
    return [_run_dict(r) for r in q.order_by(EvaluationRun.created_at.desc()).limit(max(1, min(limit, 200)))]

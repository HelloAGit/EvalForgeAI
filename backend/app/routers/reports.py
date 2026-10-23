import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models.entities import GeneratedArtifact, ReportDefinition, ReportSnapshot, VideoJob
from app.security import User, assert_owner, get_current_user
from app.services import reports as svc
from app.services.metrics_catalog import CATALOG_BY_KEY
from app.services.pdf_report import TEMPLATES
from app.services.snapshot import CHART_IDS, SnapshotError, build_payload, create_snapshot
from app.services.storage import StorageError, get_storage

logger = logging.getLogger("evalforge.reports")
router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])


class ReportIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    template: str
    project_id: str
    run_ids: Optional[List[str]] = Field(None, max_length=200)
    model_ids: Optional[List[str]] = Field(None, max_length=50)
    date_from: Optional[str] = Field(None, max_length=40)
    date_to: Optional[str] = Field(None, max_length=40)
    metrics: Optional[List[str]] = Field(None, max_length=50)
    charts: Optional[List[str]] = Field(None, max_length=20)
    include_cases: bool = False

    @field_validator("template")
    @classmethod
    def _template(cls, v):
        if v not in TEMPLATES:
            raise ValueError(f"template must be one of {sorted(TEMPLATES)}")
        return v

    @field_validator("metrics")
    @classmethod
    def _metrics(cls, v):
        bad = [m for m in (v or []) if m not in CATALOG_BY_KEY or CATALOG_BY_KEY[m].kind != "observation"]
        if bad:
            raise ValueError(f"unknown metric keys: {bad}")
        return v

    @field_validator("charts")
    @classmethod
    def _charts(cls, v):
        bad = [c for c in (v or []) if c not in CHART_IDS]
        if bad:
            raise ValueError(f"unknown chart ids: {bad}; allowed {CHART_IDS}")
        return v


def _config(body: ReportIn) -> dict:
    return body.model_dump(exclude={"title"})


def report_dict(db: Session, r: ReportDefinition, detail: bool = False) -> dict:
    arts = db.query(GeneratedArtifact).filter_by(report_id=r.id, kind="pdf").order_by(GeneratedArtifact.created_at.desc()).all()
    cur = next((a for a in arts if a.id == r.current_artifact_id), None)
    d = {"id": r.id, "title": r.title, "template": r.template, "template_name": TEMPLATES[r.template], "project_id": r.project_id,
         "status": r.status, "error_message": r.error_message, "snapshot_id": r.snapshot_id, "created_at": r.created_at.isoformat() + "Z",
         "updated_at": r.updated_at.isoformat() + "Z",
         "artifact": {"id": cur.id, "size_bytes": cur.size_bytes, "created_at": cur.created_at.isoformat() + "Z"} if cur else None,
         "video_count": db.query(VideoJob).filter_by(report_id=r.id).count()}
    if detail:
        d["config"] = r.config
        d["artifacts"] = [{"id": a.id, "size_bytes": a.size_bytes, "sha256": a.sha256, "created_at": a.created_at.isoformat() + "Z"} for a in arts]
    return d


def _get_report(db: Session, report_id: str, user: User) -> ReportDefinition:
    r = db.get(ReportDefinition, report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    assert_owner(user, r.owner_id)
    return r


def _generate_in_background(report_id: str) -> None:
    with SessionLocal() as db:
        r = db.get(ReportDefinition, report_id)
        try:
            svc.generate_pdf(db, r)
        except Exception:
            logger.exception("PDF generation failed for report %s", report_id)


@router.post("/preview")
def preview(body: ReportIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Computes what a snapshot would contain without persisting anything."""
    try:
        return {"payload": build_payload(db, user.id, _config(body), "preview")}
    except SnapshotError as exc:
        raise HTTPException(422, str(exc))


@router.post("", status_code=201)
def create_report(body: ReportIn, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cfg = _config(body)
    try:
        snap = create_snapshot(db, user.id, cfg)
    except SnapshotError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    report = ReportDefinition(owner_id=user.id, title=body.title, template=body.template, project_id=body.project_id, config=cfg,
                              status="PENDING", snapshot_id=snap.id)
    db.add(report)
    db.commit()
    background.add_task(_generate_in_background, report.id)
    return report_dict(db, report, detail=True)


@router.get("")
def list_reports(limit: int = 100, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(ReportDefinition)
    if not user.is_admin:
        q = q.filter(ReportDefinition.owner_id == user.id)
    return [report_dict(db, r) for r in q.order_by(ReportDefinition.created_at.desc()).limit(max(1, min(limit, 200)))]


@router.get("/{report_id}")
def get_report(report_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return report_dict(db, _get_report(db, report_id, user), detail=True)


@router.post("/{report_id}/regenerate", status_code=202)
def regenerate(report_id: str, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Re-renders the PDF from the ORIGINAL snapshot (figures never change)."""
    r = _get_report(db, report_id, user)
    if r.status in ("GENERATING",):
        raise HTTPException(409, "Report is already being generated")
    r.status = "PENDING"
    db.commit()
    background.add_task(_generate_in_background, r.id)
    return report_dict(db, r, detail=True)


@router.get("/{report_id}/snapshot")
def get_snapshot(report_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = _get_report(db, report_id, user)
    s = db.get(ReportSnapshot, r.snapshot_id)
    return {"id": s.id, "schema_version": s.schema_version, "payload_sha256": s.payload_sha256,
            "created_at": s.created_at.isoformat() + "Z", "payload": s.payload}


@router.get("/{report_id}/download")
def download(report_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = _get_report(db, report_id, user)
    art = db.get(GeneratedArtifact, r.current_artifact_id) if r.current_artifact_id else None
    if r.status != "COMPLETED" or art is None:
        raise HTTPException(409, f"Report is not ready (status {r.status})")
    try:
        path = get_storage().path(art.storage_key)
    except StorageError:
        raise HTTPException(500, "Invalid storage key")
    if not path.is_file():
        raise HTTPException(410, "Artifact file is missing from storage")
    return FileResponse(path, media_type="application/pdf", filename=svc.safe_filename(r.title, "pdf"),
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                                 "X-Artifact-SHA256": art.sha256})

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.entities import GeneratedArtifact, ReportDefinition, ReportSnapshot, VideoJob, utcnow
from app.security import User, assert_owner, get_current_user
from app.services import narrative
from app.services.mubit_gateway import MubitGateway
from app.services.storage import StorageError, get_storage
from app.services.tts import get_tts
from app.services.video_worker import TERMINAL, storyboard_hash

logger = logging.getLogger("evalforge.videos")
router = APIRouter(prefix="/api/v1/videos", tags=["Videos"])


class VideoIn(BaseModel):
    report_id: str
    duration_seconds: int = 120
    mode: str = "silent"
    voice: Optional[str] = Field(None, max_length=80)
    captions: bool = True
    sections: Optional[List[str]] = Field(None, max_length=len(narrative.SCENE_TYPES))

    @field_validator("duration_seconds")
    @classmethod
    def _d(cls, v):
        if v not in narrative.DURATION_TARGETS:
            raise ValueError(f"duration_seconds must be one of {list(narrative.DURATION_TARGETS)}")
        if v > settings.VIDEO_MAX_DURATION_SECONDS:
            raise ValueError("duration exceeds VIDEO_MAX_DURATION_SECONDS")
        return v

    @field_validator("mode")
    @classmethod
    def _m(cls, v):
        if v not in ("silent", "narrated"):
            raise ValueError("mode must be silent or narrated")
        return v

    @field_validator("sections")
    @classmethod
    def _s(cls, v):
        bad = [s for s in (v or []) if s not in narrative.SCENE_TYPES]
        if bad:
            raise ValueError(f"unknown sections {bad}; allowed {narrative.SCENE_TYPES}")
        return v


class ApproveIn(BaseModel):
    acknowledge_flags: bool = False


def job_dict(db: Session, j: VideoJob) -> dict:
    art = db.get(GeneratedArtifact, j.artifact_id) if j.artifact_id else None
    return {"id": j.id, "report_id": j.report_id, "state": j.state, "stage": j.stage, "progress": j.progress, "options": j.options,
            "storyboard": j.storyboard, "storyboard_source": j.storyboard_source, "validation": j.validation,
            "approved": j.approved_at is not None, "error_message": j.error_message,
            "artifact": {"id": art.id, "size_bytes": art.size_bytes, "duration_seconds": (art.meta or {}).get("duration_seconds")} if art else None,
            "created_at": j.created_at.isoformat() + "Z", "updated_at": j.updated_at.isoformat() + "Z"}


def _get(db: Session, video_id: str, user: User) -> VideoJob:
    j = db.get(VideoJob, video_id)
    if j is None:
        raise HTTPException(404, "Video not found")
    assert_owner(user, j.owner_id)
    return j


@router.get("/capabilities")
def capabilities(user: User = Depends(get_current_user)):
    tts = get_tts()
    return {"tts_available": tts.available(), "voices": tts.voices() if tts.available() else [], "renderer": "pillow+ffmpeg",
            "mubit_configured": MubitGateway().is_configured(), "max_duration_seconds": settings.VIDEO_MAX_DURATION_SECONDS,
            "resolution": f"{settings.VIDEO_WIDTH}x{settings.VIDEO_HEIGHT}", "fps": settings.VIDEO_FPS,
            "durations": list(narrative.DURATION_TARGETS), "sections": narrative.SCENE_TYPES}


@router.post("", status_code=201)
def create_video(body: VideoIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    report = db.get(ReportDefinition, body.report_id)
    if report is None:
        raise HTTPException(404, "Report not found")
    assert_owner(user, report.owner_id)
    if report.status != "COMPLETED" or not report.snapshot_id:
        raise HTTPException(409, "The report must be completed before a video can be created from it")
    if body.mode == "narrated":
        tts = get_tts()
        if not tts.available():
            raise HTTPException(422, "Narrated mode is unavailable: no TTS provider is configured (set TTS_PROVIDER).")
        if body.voice and body.voice not in tts.voices():
            raise HTTPException(422, f"Unknown voice; available: {tts.voices()}")
    active = db.query(VideoJob).filter(VideoJob.owner_id == user.id, VideoJob.state.notin_(TERMINAL)).count()
    if active >= settings.VIDEO_MAX_ACTIVE_PER_USER:
        raise HTTPException(429, f"Too many active video jobs (limit {settings.VIDEO_MAX_ACTIVE_PER_USER}); wait or cancel one.")
    job = VideoJob(owner_id=user.id, report_id=report.id, snapshot_id=report.snapshot_id, state="QUEUED", stage="Waiting for a worker",
                   options=body.model_dump())
    db.add(job)
    db.commit()
    return job_dict(db, job)


@router.get("")
def list_videos(report_id: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(VideoJob)
    if not user.is_admin:
        q = q.filter(VideoJob.owner_id == user.id)
    if report_id:
        q = q.filter(VideoJob.report_id == report_id)
    return [job_dict(db, j) for j in q.order_by(VideoJob.created_at.desc()).limit(max(1, min(limit, 200)))]


@router.get("/{video_id}")
def get_video(video_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return job_dict(db, _get(db, video_id, user))


@router.put("/{video_id}/storyboard")
def update_storyboard(video_id: str, body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """User edit before render. Re-validated against the snapshot; approval is reset."""
    j = _get(db, video_id, user)
    if j.state != "AWAITING_APPROVAL":
        raise HTTPException(409, f"Storyboard can only be edited while awaiting approval (state {j.state})")
    if isinstance(body.get("storyboard"), dict) and "scenes" not in body:
        body = body["storyboard"]  # accept {"storyboard": {...}} as well as the bare object
    try:
        sb = narrative.Storyboard.model_validate(body).normalised()
    except Exception as exc:
        raise HTTPException(422, f"Invalid storyboard: {str(exc)[:500]}")
    if sb.total_duration_seconds > settings.VIDEO_MAX_DURATION_SECONDS:
        raise HTTPException(422, "Total duration exceeds the configured maximum")
    snap = db.get(ReportSnapshot, j.snapshot_id)
    validation = narrative.validate_grounding(sb, snap.payload)
    validation["edited"] = True
    j.storyboard, j.validation = sb.model_dump(), validation
    j.approved_at = j.approved_hash = None
    j.updated_at = utcnow()
    db.commit()
    return job_dict(db, j)


@router.post("/{video_id}/approve")
def approve(video_id: str, body: Optional[ApproveIn] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    j = _get(db, video_id, user)
    if j.state != "AWAITING_APPROVAL" or not j.storyboard:
        raise HTTPException(409, f"Video is not awaiting approval (state {j.state})")
    flags = narrative.blocking_flags(j.validation)
    if flags and not (body and body.acknowledge_flags):
        raise HTTPException(409, detail={"message": "The storyboard has unsupported or ungrounded claims; fix them or acknowledge the flags.",
                                         "flags": flags})
    j.approved_at, j.approved_hash = utcnow(), storyboard_hash(j.storyboard)
    if flags:
        j.validation = {**(j.validation or {}), "acknowledged_flags": len(flags)}
    j.updated_at = utcnow()
    db.commit()
    return job_dict(db, j)


@router.post("/{video_id}/render", status_code=202)
def render(video_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Queues the render for the worker; returns immediately."""
    j = _get(db, video_id, user)
    if j.state != "AWAITING_APPROVAL":
        raise HTTPException(409, f"Video cannot be rendered from state {j.state}")
    if j.approved_at is None or j.approved_hash != storyboard_hash(j.storyboard):
        raise HTTPException(409, "Approve the storyboard before rendering")
    j.state, j.stage, j.progress, j.attempts = "RENDERING", "Waiting for a render worker", 0.0, 0
    j.locked_by = j.lease_expires_at = None
    j.updated_at = utcnow()
    db.commit()
    return job_dict(db, j)


@router.post("/{video_id}/cancel")
def cancel(video_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    j = _get(db, video_id, user)
    if j.state in TERMINAL:
        raise HTTPException(409, f"Video is already {j.state}")
    j.state, j.stage, j.completed_at = "CANCELLED", "Cancelled by user", utcnow()
    j.updated_at = utcnow()
    db.commit()
    return job_dict(db, j)


@router.get("/{video_id}/download")
def download(video_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    j = _get(db, video_id, user)
    art = db.get(GeneratedArtifact, j.artifact_id) if j.artifact_id else None
    if j.state != "COMPLETED" or art is None:
        raise HTTPException(409, f"Video is not ready (state {j.state})")
    try:
        path = get_storage().path(art.storage_key)
    except StorageError:
        raise HTTPException(500, "Invalid storage key")
    if not path.is_file():
        raise HTTPException(410, "Artifact file is missing from storage")
    return FileResponse(path, media_type="video/mp4", filename=f"evalforge-briefing-{j.id[:8]}.mp4",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "X-Artifact-SHA256": art.sha256})

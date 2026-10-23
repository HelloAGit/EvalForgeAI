"""Durable video job processing (runs in the worker process, never in a request handler).

States: QUEUED -> GENERATING_SCRIPT -> AWAITING_APPROVAL -> (approve) -> RENDERING -> COMPLETED,
with FAILED and CANCELLED reachable from any non-terminal state. Claims are atomic compare-and-set
updates with a lease, so several workers can run safely and a crashed worker's job is recovered
once its lease expires (bounded by VIDEO_MAX_ATTEMPTS).
"""
import hashlib
import json
import logging
import os
import shutil
import tempfile
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.models.entities import GeneratedArtifact, ReportSnapshot, VideoJob, utcnow
from app.services import narrative
from app.services.mubit_gateway import MubitGateway
from app.services.storage import get_storage
from app.services.tts import TTSError, get_tts

logger = logging.getLogger("evalforge.video")
TERMINAL = ("COMPLETED", "FAILED", "CANCELLED")
SCRIPT_STATES = ("GENERATING_SCRIPT",)
RENDER_STATES = ("RENDERING",)


def storyboard_hash(storyboard: Optional[dict]) -> str:
    return hashlib.sha256(json.dumps(storyboard, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _lease():
    return utcnow() + timedelta(seconds=settings.WORKER_LEASE_SECONDS)


def recover_expired(db: Session) -> int:
    """Jobs whose worker vanished: retry while attempts remain, otherwise fail with a clear message."""
    n = 0
    now = utcnow()
    for job in db.query(VideoJob).filter(VideoJob.state.in_(SCRIPT_STATES + RENDER_STATES), VideoJob.locked_by.isnot(None),
                                         VideoJob.lease_expires_at < now).all():
        if job.attempts >= settings.VIDEO_MAX_ATTEMPTS:
            _set(db, job, state="FAILED", error_message="Worker stopped responding and the retry limit was reached.", locked_by=None,
                 lease_expires_at=None, completed_at=utcnow())
        else:
            _set(db, job, state="QUEUED" if job.state == "GENERATING_SCRIPT" else "RENDERING", stage="re-queued after worker timeout",
                 locked_by=None, lease_expires_at=None)
        n += 1
    return n


def _set(db: Session, job: VideoJob, **vals) -> None:
    for k, v in vals.items():
        setattr(job, k, v)
    job.updated_at = utcnow()
    db.commit()


def _claim(db: Session, state: str, worker_id: str, new_state: str, stage: str) -> Optional[VideoJob]:
    cand = (db.query(VideoJob.id).filter(VideoJob.state == state, VideoJob.locked_by.is_(None))
            .order_by(VideoJob.created_at).limit(5).all())
    for (jid,) in cand:
        res = db.execute(update(VideoJob).where(VideoJob.id == jid, VideoJob.state == state, VideoJob.locked_by.is_(None))
                         .values(state=new_state, stage=stage, locked_by=worker_id, lease_expires_at=_lease(),
                                 attempts=VideoJob.attempts + 1, updated_at=utcnow()))
        db.commit()
        if res.rowcount == 1:
            job = db.get(VideoJob, jid)
            db.refresh(job)
            return job
    return None


def process_next(db: Session, worker_id: str, gateway: Any = None, renderer: Any = None, tts: Any = None) -> int:
    """Handles at most one script job and one render job. Returns the number handled."""
    recover_expired(db)
    done = 0
    job = _claim(db, "QUEUED", worker_id, "GENERATING_SCRIPT", "Generating storyboard")
    if job:
        _generate_script(db, job, gateway)
        done += 1
    job = _claim(db, "RENDERING", worker_id, "RENDERING", "Preparing render")
    if job:
        _render(db, job, renderer, tts)
        done += 1
    return done


def _is_cancelled(db: Session, job_id: str) -> bool:
    db.expire_all()
    state = db.query(VideoJob.state).filter(VideoJob.id == job_id).scalar()
    return state == "CANCELLED"


def _generate_script(db: Session, job: VideoJob, gateway: Any) -> None:
    job_id = job.id
    try:
        snap = db.get(ReportSnapshot, job.snapshot_id)
        sb, source, validation = narrative.generate_storyboard(snap.payload, job.options, gateway or MubitGateway())
        if _is_cancelled(db, job_id):
            return
        job = db.get(VideoJob, job_id)
        _set(db, job, storyboard=sb.model_dump(), storyboard_source=source, validation=validation, state="AWAITING_APPROVAL",
             stage="Waiting for script review", progress=0.0, locked_by=None, lease_expires_at=None, error_message=None)
    except Exception as exc:
        logger.exception("script generation failed for %s", job_id)
        db.rollback()
        job = db.get(VideoJob, job_id)
        if job.state == "CANCELLED":
            return
        retry = job.attempts < settings.VIDEO_MAX_ATTEMPTS
        _set(db, job, state="QUEUED" if retry else "FAILED", stage="retrying" if retry else "failed", locked_by=None, lease_expires_at=None,
             error_message=f"Script generation failed: {type(exc).__name__}: {exc}"[:500], completed_at=None if retry else utcnow())


def _render(db: Session, job: VideoJob, renderer: Any, tts: Any) -> None:
    from app.services import video_renderer  # lazy: keeps Pillow/ffmpeg out of the web image
    job_id = job.id
    workdir = None
    renderer = renderer or video_renderer.PillowRenderer()
    last_commit = [0.0]

    def cancel_check():
        if _is_cancelled(db, job_id):
            raise video_renderer.RenderCancelled()

    def progress(frac: float, stage: str = "Rendering frames"):
        j = db.get(VideoJob, job_id)
        j.progress = round(min(0.95, 0.05 + frac * 0.9), 3)
        j.stage = stage
        j.lease_expires_at = _lease()
        j.updated_at = utcnow()
        db.commit()

    try:
        db.refresh(job)
        if job.approved_at is None or job.approved_hash != storyboard_hash(job.storyboard):
            raise video_renderer.RenderError("Storyboard is not approved (or was edited after approval).")
        snap = db.get(ReportSnapshot, job.snapshot_id)
        payload = snap.payload
        sb = narrative.Storyboard.model_validate(job.storyboard)
        opts = job.options
        tmp_root = os.path.join(str(get_storage().root), "tmp")
        os.makedirs(tmp_root, exist_ok=True)
        workdir = tempfile.mkdtemp(prefix=f"video-{job_id[:8]}-", dir=tmp_root)
        audio_path, durations = None, None
        if opts.get("mode") == "narrated":
            provider = tts or get_tts()
            if not provider.available():
                raise TTSError("Narrated mode requested but no TTS provider is configured.")
            progress(0.0, "Synthesising narration")
            audio_path, durations = video_renderer.plan_narration(sb, provider, opts.get("voice") or (provider.voices() or ["default"])[0],
                                                                  workdir, cancel_check)
        out = os.path.join(workdir, "briefing.mp4")
        cancel_check()
        res = renderer.render(payload, sb, out, captions=bool(opts.get("captions", True)), audio_path=audio_path,
                              scene_durations=durations, progress=progress, cancel_check=cancel_check,
                              timeout=settings.VIDEO_RENDER_TIMEOUT_SECONDS)
        progress(1.0, "Validating output")
        info = video_renderer.validate_mp4(res.path, expected_duration=res.duration_seconds, width=res.width, height=res.height,
                                           audio=res.has_audio)
        cancel_check()
        storage = get_storage()
        key = storage.new_key("video", "mp4")
        size, sha = storage.put_file(key, res.path)
        art = GeneratedArtifact(owner_id=job.owner_id, kind="video", report_id=job.report_id, snapshot_id=job.snapshot_id,
                                video_id=job_id, storage_key=key, content_type="video/mp4", size_bytes=size, sha256=sha,
                                meta={"duration_seconds": info["duration"], "width": info["width"], "height": info["height"],
                                      "fps": info["fps"], "audio": info["has_audio"], "storyboard_source": job.storyboard_source,
                                      "storyboard_sha256": job.approved_hash, "snapshot_sha256": snap.payload_sha256})
        db.add(art)
        db.flush()
        if _is_cancelled(db, job_id):
            storage.delete(key)
            db.rollback()
            return
        job = db.get(VideoJob, job_id)
        _set(db, job, artifact_id=art.id, state="COMPLETED", stage="Completed", progress=1.0, locked_by=None,
             lease_expires_at=None, completed_at=utcnow(), error_message=None)
    except video_renderer.RenderCancelled:
        db.rollback()
        job = db.get(VideoJob, job_id)
        if job.state != "CANCELLED":
            _set(db, job, state="CANCELLED", stage="Cancelled", locked_by=None, lease_expires_at=None, completed_at=utcnow())
    except Exception as exc:
        logger.exception("render failed for %s", job_id)
        db.rollback()
        job = db.get(VideoJob, job_id)
        if job.state == "CANCELLED":
            return
        transient = not isinstance(exc, (video_renderer.RenderTimeout, TTSError)) and not (
            isinstance(exc, video_renderer.RenderError) and "not approved" in str(exc))
        retry = transient and job.attempts < settings.VIDEO_MAX_ATTEMPTS
        msg = f"{type(exc).__name__}: {exc}"[:500]
        if retry:
            _set(db, job, state="RENDERING", stage="retrying after error", locked_by=None, lease_expires_at=None, error_message=msg)
        else:
            _set(db, job, state="FAILED", stage="Failed", locked_by=None, lease_expires_at=None, error_message=msg, completed_at=utcnow())
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)

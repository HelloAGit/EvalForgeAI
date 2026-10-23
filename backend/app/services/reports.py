import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.entities import GeneratedArtifact, ReportDefinition, ReportSnapshot, utcnow
from app.services.pdf_report import render_pdf
from app.services.storage import get_storage


def generate_pdf(db: Session, report: ReportDefinition) -> GeneratedArtifact:
    """Render the PDF from the report's immutable snapshot and persist it. Never recomputes metrics."""
    snap = db.get(ReportSnapshot, report.snapshot_id)
    report.status, report.error_message = "GENERATING", None
    db.commit()
    try:
        data = render_pdf(snap.payload, report.template, report.title, report.id, utcnow().isoformat() + "Z")
        storage = get_storage()
        key = storage.new_key("pdf", "pdf")
        size, sha = storage.put_bytes(key, data)
        art = GeneratedArtifact(owner_id=report.owner_id, kind="pdf", report_id=report.id, snapshot_id=snap.id, storage_key=key,
                                content_type="application/pdf", size_bytes=size, sha256=sha,
                                meta={"template": report.template, "snapshot_sha256": snap.payload_sha256})
        db.add(art)
        db.flush()
        report.current_artifact_id, report.status = art.id, "COMPLETED"
        db.commit()
        return art
    except Exception as exc:
        db.rollback()
        report = db.get(ReportDefinition, report.id)
        report.status, report.error_message = "FAILED", f"{type(exc).__name__}: {exc}"[:500]
        db.commit()
        raise


def safe_filename(title: str, ext: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-.")[:60] or "report"
    return f"{slug}.{ext}"

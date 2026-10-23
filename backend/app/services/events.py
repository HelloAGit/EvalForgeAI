"""Database-backed change events (the single source for live dashboard updates).

Each write that changes dashboard-visible data appends one ``EvaluationEvent``.
Its autoincrement id is the SSE ``id`` used for de-duplication and for
resynchronisation after a missed connection. Streaming only needs a cheap
``id > last_id`` primary-key range query.
"""
import asyncio
import json
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.entities import EvaluationEvent


def emit_event(db: Session, event_type: str, project_id: Optional[str] = None,
               run_id: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> EvaluationEvent:
    ev = EvaluationEvent(event_type=event_type, project_id=project_id, run_id=run_id, payload=payload or {})
    db.add(ev)
    db.flush()
    return ev


def latest_event_id(db: Session) -> int:
    return int(db.scalar(select(func.max(EvaluationEvent.id))) or 0)


def event_to_dict(ev: EvaluationEvent) -> Dict[str, Any]:
    return {"id": ev.id, "type": ev.event_type, "project_id": ev.project_id, "run_id": ev.run_id,
            "payload": ev.payload or {}, "created_at": ev.created_at.isoformat() + "Z"}


def events_after(db: Session, after: int, limit: int = 100) -> List[Dict[str, Any]]:
    rows = db.scalars(select(EvaluationEvent).where(EvaluationEvent.id > after)
                      .order_by(EvaluationEvent.id).limit(limit)).all()
    return [event_to_dict(r) for r in rows]


def gap_exceeds_catchup(db: Session, after: int) -> bool:
    """True when too many events were missed for incremental replay (client must resync)."""
    latest = latest_event_id(db)
    return after > latest or (latest - after) > settings.SSE_MAX_CATCHUP_EVENTS


def format_sse(event_id: Optional[int], event: str, data: Dict[str, Any]) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(data, separators=(",", ":")))
    return "\n".join(lines) + "\n\n"


async def sse_stream(session_factory: Callable[[], Session], after: int, max_seconds: float,
                     is_disconnected: Optional[Callable[[], Any]] = None) -> AsyncIterator[str]:
    """Yield SSE frames. Sends ``resync`` when the client is too far behind (or ahead,
    e.g. after a database reset), then incremental ``evaluation`` events, plus heartbeats."""
    loop = asyncio.get_event_loop()
    started = loop.time()
    last_beat = started
    last_id = after

    def _poll(cursor: int):
        with session_factory() as db:
            if gap_exceeds_catchup(db, cursor):
                return "resync", latest_event_id(db), []
            return "ok", cursor, events_after(db, cursor)

    yield "retry: 3000\n\n"
    while loop.time() - started < max_seconds:
        if is_disconnected is not None and await is_disconnected():
            return
        status, cursor, events = await asyncio.to_thread(_poll, last_id)
        if status == "resync":
            last_id = cursor
            yield format_sse(cursor, "resync", {"last_event_id": cursor})
        for ev in events:
            last_id = ev["id"]
            yield format_sse(ev["id"], "evaluation", ev)
        now = loop.time()
        if not events and now - last_beat >= settings.SSE_HEARTBEAT_SECONDS:
            last_beat = now
            yield ": heartbeat\n\n"
        elif events:
            last_beat = now
        await asyncio.sleep(settings.SSE_POLL_SECONDS)
    yield format_sse(None, "reconnect", {"reason": "max_duration", "last_event_id": last_id})

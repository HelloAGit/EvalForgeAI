import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.models.entities import DashboardPreference
from app.security import User, get_current_user
from app.services import dashboard as svc
from app.services.events import (
    events_after, gap_exceeds_catchup, latest_event_id, sse_stream,
)
from app.services.metrics_catalog import CATALOG, CATALOG_VERSION, quality_weights

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


def filters(project_id: Optional[str] = None, provider: Optional[str] = None, model_id: Optional[str] = None,
            suite: Optional[str] = None, dataset_version: Optional[str] = None, run_id: Optional[str] = None,
            category: Optional[str] = Query(None, pattern="^(llm|rag|agent)$"),
            status: Optional[str] = Query(None, pattern="^(PASSED|FAILED|ERROR|COMPLETED)$"),
            date_from: Optional[str] = None, date_to: Optional[str] = None) -> svc.Filters:
    try:
        return svc.Filters(project_id=project_id, provider=provider, model_id=model_id, suite=suite,
                           dataset_version=dataset_version, run_id=run_id, category=category, status=status,
                           date_from=svc.parse_date(date_from), date_to=svc.parse_date(date_to, end_of_day=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Backwards-compatible 2.0 summary, now computed from persisted data."""
    return svc.legacy_summary(db)


@router.get("/overview")
def overview(f: svc.Filters = Depends(filters), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.overview(db, f)


@router.get("/metrics")
def metrics(f: svc.Filters = Depends(filters), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """KPI catalogue plus current values (value=null + na_reason when unsupported/insufficient)."""
    kpis, ctx = svc.build_kpis(db, f)
    weights = quality_weights()
    by_key = {k["key"]: k for k in kpis}
    items = []
    for m in CATALOG:
        d = m.public()
        d["qi_weight"] = weights.get(m.key, 0.0)
        d["current"] = by_key[m.key]
        items.append(d)
    return {"catalog_version": CATALOG_VERSION, "metrics": items, "quality_index": ctx["qi"],
            "last_event_id": latest_event_id(db), "filters": f.public()}


@router.get("/metrics/{metric_key}")
def metric_detail(metric_key: str, f: svc.Filters = Depends(filters), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    try:
        return svc.metric_detail(db, f, metric_key)
    except KeyError:
        raise HTTPException(404, f"Unknown metric {metric_key!r}")


@router.get("/trends")
def trends(metric: str = "quality_index", bucket: str = "day", f: svc.Filters = Depends(filters),
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return svc.trends(db, f, metric, bucket)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/alerts")
def alerts(f: svc.Filters = Depends(filters), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"alerts": svc.regression_alerts(db, f), "last_event_id": latest_event_id(db),
            "threshold": settings.REGRESSION_DROP_THRESHOLD}


@router.get("/compare")
def compare(a_model_id: Optional[str] = None, a_run_id: Optional[str] = None,
            b_model_id: Optional[str] = None, b_run_id: Optional[str] = None,
            f: svc.Filters = Depends(filters), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = {k: v for k, v in (("model_id", a_model_id), ("run_id", a_run_id)) if v}
    b = {k: v for k, v in (("model_id", b_model_id), ("run_id", b_run_id)) if v}
    try:
        return svc.compare(db, f, a, b)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/events")
async def events(request: Request, after: Optional[int] = Query(None, ge=0), stream: bool = False,
                 max_seconds: Optional[float] = Query(None, gt=0, le=3600),
                 last_event_id: Optional[str] = Header(default=None), user: User = Depends(get_current_user)):
    """Change events. ``stream=true`` (or Accept: text/event-stream) returns Server-Sent Events;
    otherwise a JSON page for polling clients. ``after`` / Last-Event-ID resume the stream."""
    cursor = after
    if cursor is None and last_event_id and last_event_id.isdigit():
        cursor = int(last_event_id)
    wants_stream = stream or "text/event-stream" in (request.headers.get("accept") or "")
    if not wants_stream:
        with SessionLocal() as db:
            latest = latest_event_id(db)
            if cursor is None:
                return {"events": [], "last_event_id": latest, "resync": False}
            if gap_exceeds_catchup(db, cursor):
                return {"events": [], "last_event_id": latest, "resync": True}
            evs = events_after(db, cursor, 100)
            return {"events": evs, "last_event_id": evs[-1]["id"] if evs else cursor, "resync": False}
    if cursor is None:
        with SessionLocal() as db:
            cursor = latest_event_id(db)
    duration = min(max_seconds or settings.SSE_MAX_DURATION_SECONDS, settings.SSE_MAX_DURATION_SECONDS)
    return StreamingResponse(
        sse_stream(SessionLocal, cursor, duration, request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


DEFAULT_PREFS = {"visible_kpis": [], "default_filters": {}, "auto_refresh": True}


@router.get("/preferences")
def get_preferences(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(DashboardPreference).filter_by(user_id=user.id).one_or_none()
    return row.preferences if row else DEFAULT_PREFS


@router.put("/preferences")
def put_preferences(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    unknown = [k for k in body.get("visible_kpis", []) if k not in {m.key for m in CATALOG}]
    if unknown:
        raise HTTPException(422, f"Unknown KPI keys: {unknown}")
    if len(json.dumps(body)) > 20_000:
        raise HTTPException(413, "Preferences too large")
    prefs = {**DEFAULT_PREFS, **{k: v for k, v in body.items() if k in DEFAULT_PREFS}}
    row = db.query(DashboardPreference).filter_by(user_id=user.id).one_or_none()
    if row is None:
        db.add(DashboardPreference(user_id=user.id, preferences=prefs))
    else:
        row.preferences = prefs
    db.commit()
    return prefs

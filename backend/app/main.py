import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import dashboard, evaluations, health, mubit, reports, schedules, statistics

logger = logging.getLogger("evalforge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.AUTO_MIGRATE:
        from app.migrations import upgrade_database
        upgrade_database()
    stop = threading.Event()
    thread = None
    if settings.WORKER_INLINE:  # development convenience only; production runs `python -m app.worker`
        from app.worker import run_forever
        thread = threading.Thread(target=run_forever, args=(stop,), daemon=True, name="inline-worker")
        thread.start()
    yield
    stop.set()
    if thread:
        thread.join(timeout=10)


app = FastAPI(
    title="EvalForge AI 3.0 Backend",
    description="Statistical Intelligence & AI Quality Evaluation Engine with live dashboard, PDF reports and video briefings",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
    expose_headers=["Content-Disposition"],
)

app.include_router(health.router)
app.include_router(mubit.router)
app.include_router(statistics.router)
app.include_router(dashboard.router)
app.include_router(evaluations.router)
app.include_router(schedules.router)
app.include_router(reports.router)

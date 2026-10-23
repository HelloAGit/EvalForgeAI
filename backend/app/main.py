import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app.routers import health, mubit, statistics
from app.seed.demo_data import DEMO_KPI_SUMMARY

# Initialize Database Schema
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="EvalForge AI 2.0 Backend",
    description="Statistical Intelligence & AI Quality Evaluation Engine",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(mubit.router)
app.include_router(statistics.router)

@app.get("/api/v1/dashboard/summary")
async def get_dashboard_summary():
    return DEMO_KPI_SUMMARY

# Serve the statically exported frontend (single-image deployment) when present.
# Mounted last so API routes take precedence.
_static_dir = Path(os.environ.get("STATIC_DIR", "")) if os.environ.get("STATIC_DIR") else None
if _static_dir and _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="frontend")

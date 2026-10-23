from fastapi import APIRouter
from app.config import settings
from app.services.mubit_client import MubitClient

router = APIRouter(tags=["Health"])

@router.get("/health")
@router.get("/api/v1/health")
async def health_check():
    mubit = MubitClient()
    return {
        "status": "healthy",
        "environment": settings.APP_ENV,
        "mubit_configured": mubit.is_configured()
    }

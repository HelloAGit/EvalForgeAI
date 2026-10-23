from fastapi import APIRouter
from app.services.mubit_client import MubitClient
from app.config import settings

router = APIRouter(prefix="/api/v1/mubit", tags=["Mubit Integration"])

@router.get("/status")
async def mubit_status():
    client = MubitClient()
    conn = await client.test_connection()
    return {
        "configured": client.is_configured(),
        "base_url": settings.MUBIT_ANTHROPIC_BASE_URL,
        "model": settings.MUBIT_ANTHROPIC_MODEL,
        "connection_active": conn.get("active", False),
        "message": conn.get("message", "")
    }

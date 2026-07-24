"""Health endpoints."""

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from incident_api import __version__
from incident_api.config import settings
from incident_api.db import engine

router = APIRouter()


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "alive", "version": __version__}


@router.get("/health/ready")
async def readiness(response: Response) -> dict[str, str]:
    if not settings.is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "reason": "database_url not configured"}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — surface readiness failure
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "reason": f"database: {exc.__class__.__name__}"}
    return {"status": "ready", "version": __version__}

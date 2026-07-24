"""Health endpoints."""

from fastapi import APIRouter
from sqlalchemy import text

from remediation_controller import __version__
from remediation_controller.db import SessionLocal

router = APIRouter()


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive", "version": __version__}


@router.get("/health/ready")
async def ready() -> dict[str, str]:
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ready", "version": __version__}

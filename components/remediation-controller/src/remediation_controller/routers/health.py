"""Health endpoints."""

from fastapi import APIRouter

from remediation_controller import __version__

router = APIRouter()


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive", "version": __version__}


@router.get("/health/ready")
async def ready() -> dict[str, str]:
    return {"status": "ready", "version": __version__}

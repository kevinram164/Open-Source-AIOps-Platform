"""Health check endpoints."""

from fastapi import APIRouter, Response, status

from rca_agent import __version__
from rca_agent.config import settings

router = APIRouter()


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """Liveness probe — process is running."""
    return {"status": "alive", "version": __version__}


@router.get("/health/ready")
async def readiness(response: Response) -> dict[str, str]:
    """Readiness probe — dependencies available."""
    if not settings.is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        provider = settings.llm_provider or "openai"
        reason = (
            "OLLAMA_BASE_URL not configured"
            if provider.lower() == "ollama"
            else "OPENAI_API_KEY not configured"
        )
        return {"status": "not_ready", "reason": reason, "llm_provider": provider}

    return {
        "status": "ready",
        "version": __version__,
        "llm_provider": settings.llm_provider,
    }

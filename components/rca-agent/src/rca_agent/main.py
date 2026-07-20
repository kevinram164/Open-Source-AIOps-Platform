"""FastAPI application factory."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from rca_agent import __version__
from rca_agent.config import settings
from rca_agent.logging import setup_logging
from rca_agent.routers import health, metrics


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="RCA Agent",
        description="Root Cause Analysis Agent for Open Source AIOps Platform",
        version=__version__,
        lifespan=lifespan,
    )

    app.include_router(health.router, tags=["health"])
    app.include_router(metrics.router, tags=["metrics"])

    # Phase 3: app.include_router(analyze.router, prefix="/api/v1", tags=["analyze"])

    # Mount Prometheus metrics at /metrics
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": "rca-agent",
            "version": __version__,
            "status": "skeleton",
            "environment": settings.platform_environment,
        }

    return app

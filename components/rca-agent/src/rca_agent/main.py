"""FastAPI application factory."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from rca_agent import __version__
from rca_agent.config import settings
from rca_agent.logging import setup_logging
from rca_agent.observability import instrument_fastapi
from rca_agent.routers import analyze, health, metrics, ops


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="RCA Agent",
        description="Root Cause Analysis Agent for Open Source AIOps Platform",
        version=__version__,
        lifespan=lifespan,
    )
    instrument_fastapi(app, "rca-agent")
    app.include_router(health.router, tags=["health"])
    app.include_router(metrics.router, tags=["metrics"])
    app.include_router(analyze.router, tags=["analyze"])
    app.include_router(ops.router, tags=["ops"])
    app.mount("/metrics", make_asgi_app())

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": "rca-agent",
            "version": __version__,
            "status": "phase3",
            "environment": settings.platform_environment,
        }

    return app

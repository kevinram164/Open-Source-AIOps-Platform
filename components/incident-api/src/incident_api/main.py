"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from prometheus_client import make_asgi_app

from incident_api import __version__
from incident_api.config import settings
from incident_api.db import init_db
from incident_api.logging import setup_logging
from incident_api.routers import alerts, health, incidents

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    if settings.is_ready:
        try:
            await init_db()
            log.info("database_schema_ready")
        except Exception as exc:  # noqa: BLE001 — keep process up; readiness will fail
            log.error("database_init_failed", error=str(exc), error_type=type(exc).__name__)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Incident API",
        description="Incident CRUD and Alertmanager ingestion for Open Source AIOps Platform",
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(health.router, tags=["health"])
    app.include_router(incidents.router, tags=["incidents"])
    app.include_router(alerts.router, tags=["alerts"])
    app.mount("/metrics", make_asgi_app())

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": "incident-api",
            "version": __version__,
            "status": "phase2",
            "environment": settings.platform_environment,
        }

    return app

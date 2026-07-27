"""FastAPI app."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from remediation_controller import __version__
from remediation_controller.config import settings
from remediation_controller.db import init_db
from remediation_controller.observability import instrument_fastapi
from remediation_controller.routers import health, remediations


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Remediation Controller",
        description="AIOps Phase 4 — Policy Mode B (approve → K8s / GitOps PR / Ansible runbook)",
        version=__version__,
        lifespan=lifespan,
    )
    instrument_fastapi(app, "remediation-controller")
    app.include_router(health.router, tags=["health"])
    app.include_router(remediations.router, tags=["remediations"])

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": "remediation-controller",
            "version": __version__,
            "status": "phase4-complete",
            "policyMode": "B",
            "environment": settings.platform_environment,
        }

    return app

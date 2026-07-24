"""Incident CRUD + RCA trigger."""

from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_api.config import settings
from incident_api.db import get_session
from incident_api.models import Incident, IncidentStatus
from incident_api.schemas import IncidentCreate, IncidentOut, IncidentUpdate

router = APIRouter(prefix="/api/v1")


@router.post("/incidents", response_model=IncidentOut)
async def create_incident(
    body: IncidentCreate, session: AsyncSession = Depends(get_session)
) -> Incident:
    incident = Incident(
        external_id=f"INC-{uuid4().hex[:8].upper()}",
        title=body.title,
        severity=body.severity,
        namespace=body.namespace,
        workload=body.workload,
        alert_fingerprints=body.alert_fingerprints,
        labels=body.labels,
    )
    session.add(incident)
    await session.commit()
    await session.refresh(incident)
    return incident


@router.get("/incidents", response_model=list[IncidentOut])
async def list_incidents(
    status_filter: IncidentStatus | None = Query(None, alias="status"),
    namespace: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[Incident]:
    stmt = select(Incident).order_by(Incident.created_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(Incident.status == status_filter)
    if namespace:
        stmt = stmt.where(Incident.namespace == namespace)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/incidents/{incident_id}", response_model=IncidentOut)
async def get_incident(
    incident_id: UUID, session: AsyncSession = Depends(get_session)
) -> Incident:
    incident = await session.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident


@router.patch("/incidents/{incident_id}", response_model=IncidentOut)
async def update_incident(
    incident_id: UUID,
    body: IncidentUpdate,
    session: AsyncSession = Depends(get_session),
) -> Incident:
    incident = await session.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")
    if body.status is not None:
        incident.status = body.status
    if body.severity is not None:
        incident.severity = body.severity
    if body.title is not None:
        incident.title = body.title
    await session.commit()
    await session.refresh(incident)
    return incident


@router.post("/incidents/{incident_id}/analyze")
async def trigger_analyze(incident_id: UUID, session: AsyncSession = Depends(get_session)) -> dict:
    """Call RCA Agent and mark incident analyzed."""
    incident = await session.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")

    incident.status = IncidentStatus.analyzing
    await session.commit()

    payload = {
        "incident_id": str(incident.id),
        "external_id": incident.external_id,
        "title": incident.title,
        "namespace": incident.namespace,
        "workload": incident.workload,
        "severity": incident.severity.value if incident.severity else None,
        "labels": incident.labels or {},
        "alert_fingerprints": incident.alert_fingerprints or [],
        "raw_alerts": incident.raw_alerts or [],
    }
    rca_url = f"{settings.rca_agent_url.rstrip('/')}/api/v1/analyze"
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(rca_url, json=payload)
            if resp.status_code >= 400:
                incident.status = IncidentStatus.open
                await session.commit()
                raise HTTPException(
                    status_code=502,
                    detail=f"RCA agent HTTP {resp.status_code}: {resp.text[:300]}",
                )
            result = resp.json()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        incident.status = IncidentStatus.open
        await session.commit()
        raise HTTPException(status_code=502, detail=f"RCA agent error: {exc}") from exc

    incident.status = IncidentStatus.analyzed
    await session.commit()
    return {
        "incident_id": str(incident.id),
        "external_id": incident.external_id,
        "status": incident.status.value,
        "rca": result,
    }

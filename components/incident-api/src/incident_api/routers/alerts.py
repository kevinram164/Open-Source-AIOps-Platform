"""Alertmanager webhook ingestion."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from incident_api.correlation import ingest_alertmanager_payload
from incident_api.db import get_session
from incident_api.schemas import AlertmanagerWebhook, IncidentOut

router = APIRouter(prefix="/api/v1")


@router.post("/alerts", response_model=IncidentOut)
async def receive_alerts(
    payload: AlertmanagerWebhook, session: AsyncSession = Depends(get_session)
) -> IncidentOut:
    try:
        incident = await ingest_alertmanager_payload(session, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IncidentOut.model_validate(incident)

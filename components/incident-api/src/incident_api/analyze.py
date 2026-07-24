"""Shared RCA analyze + NBA persistence."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from incident_api.config import settings
from incident_api.models import Incident, IncidentStatus, RcaResult
from incident_api.nba import create_pending_remediations, map_rca_to_drafts


async def run_analyze(session: AsyncSession, incident: Incident) -> dict[str, Any]:
    """Call RCA agent, persist RcaResult, create NBA pending remediations."""
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

    drafts = map_rca_to_drafts(
        incident_external_id=incident.external_id,
        incident_namespace=incident.namespace,
        incident_workload=incident.workload,
        rca=result if isinstance(result, dict) else {},
    )
    nba = await create_pending_remediations(drafts)
    session.add(
        RcaResult(
            incident_id=incident.id,
            result={**(result if isinstance(result, dict) else {"raw": result}), "nba": nba},
            confidence=(result.get("confidence") if isinstance(result, dict) else None),
        )
    )
    await session.commit()

    return {
        "incident_id": str(incident.id),
        "external_id": incident.external_id,
        "status": incident.status.value,
        "rca": result,
        "nba": {
            "drafts_requested": drafts,
            "remediations": nba,
        },
    }

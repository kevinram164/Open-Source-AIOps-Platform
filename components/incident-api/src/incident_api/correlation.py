"""Alert → incident correlation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_api.config import settings
from incident_api.models import Incident, IncidentSeverity, IncidentStatus

log = structlog.get_logger()

_SEVERITY_MAP = {
    "critical": IncidentSeverity.critical,
    "error": IncidentSeverity.high,
    "warning": IncidentSeverity.medium,
    "info": IncidentSeverity.low,
    "none": IncidentSeverity.low,
}


def _severity_from_alert(alert: dict) -> IncidentSeverity:
    labels = alert.get("labels") or {}
    raw = (labels.get("severity") or labels.get("Severity") or "warning").lower()
    return _SEVERITY_MAP.get(raw, IncidentSeverity.medium)


def _fingerprint(alert: dict) -> str:
    if fp := alert.get("fingerprint"):
        return str(fp)
    labels = alert.get("labels") or {}
    parts = [
        labels.get("alertname", "unknown"),
        labels.get("namespace", ""),
        labels.get("pod", labels.get("deployment", labels.get("job", ""))),
    ]
    return "|".join(parts)


def _workload(alert: dict) -> str | None:
    labels = alert.get("labels") or {}
    for key in ("deployment", "statefulset", "daemonset", "pod", "job", "service"):
        if labels.get(key):
            return str(labels[key])
    return None


async def ingest_alertmanager_payload(session: AsyncSession, payload: dict) -> Incident:
    """Group alerts into an open incident within the correlation window."""
    alerts = payload.get("alerts") or []
    if not alerts:
        raise ValueError("no alerts in payload")

    fingerprints = sorted({_fingerprint(a) for a in alerts})
    primary = alerts[0]
    labels = {**(payload.get("commonLabels") or {}), **(primary.get("labels") or {})}
    namespace = labels.get("namespace")
    title = (
        (payload.get("commonAnnotations") or {}).get("summary")
        or (primary.get("annotations") or {}).get("summary")
        or labels.get("alertname")
        or "Alertmanager incident"
    )
    severity = _severity_from_alert(primary)
    window_start = datetime.now(UTC) - timedelta(seconds=settings.correlation_time_window_seconds)

    # Find open incident sharing any fingerprint in window
    result = await session.execute(
        select(Incident)
        .where(Incident.status == IncidentStatus.open)
        .where(Incident.created_at >= window_start)
        .order_by(Incident.created_at.desc())
    )
    for existing in result.scalars().all():
        existing_fps = set(existing.alert_fingerprints or [])
        if existing_fps.intersection(fingerprints):
            merged = list(dict.fromkeys([*(existing.alert_fingerprints or []), *fingerprints]))
            if len(merged) > settings.correlation_max_alerts_per_incident:
                merged = merged[: settings.correlation_max_alerts_per_incident]
            existing.alert_fingerprints = merged
            existing.raw_alerts = [*(existing.raw_alerts or []), *alerts]
            existing.updated_at = datetime.now(UTC)
            if _severity_rank(severity) > _severity_rank(existing.severity):
                existing.severity = severity
            await session.commit()
            await session.refresh(existing)
            log.info("incident_correlated", external_id=existing.external_id, fingerprints=merged)
            return existing

    seq = uuid4().hex[:8].upper()
    incident = Incident(
        external_id=f"INC-{seq}",
        title=str(title)[:500],
        status=IncidentStatus.open,
        severity=severity,
        namespace=namespace,
        workload=_workload(primary),
        alert_fingerprints=fingerprints,
        labels=labels,
        raw_alerts=alerts,
    )
    session.add(incident)
    await session.commit()
    await session.refresh(incident)
    log.info("incident_created", external_id=incident.external_id, fingerprints=fingerprints)
    return incident


def _severity_rank(sev: IncidentSeverity) -> int:
    order = {
        IncidentSeverity.low: 1,
        IncidentSeverity.medium: 2,
        IncidentSeverity.high: 3,
        IncidentSeverity.critical: 4,
    }
    return order.get(sev, 0)

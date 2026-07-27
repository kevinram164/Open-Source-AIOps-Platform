"""Alert → incident correlation (fingerprint + topology path)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
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


async def _topology_related(
    ns_a: str | None,
    wl_a: str | None,
    ns_b: str | None,
    wl_b: str | None,
) -> bool:
    if not settings.correlation_topology_enabled:
        return False
    if not wl_a or not wl_b:
        return False
    if ns_a == ns_b and wl_a == wl_b:
        return True
    url = settings.rca_agent_url.rstrip("/") + "/api/v1/topology/related"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                url,
                json={
                    "namespace_a": ns_a,
                    "workload_a": wl_a,
                    "namespace_b": ns_b,
                    "workload_b": wl_b,
                    "hops": 2,
                },
            )
            if resp.status_code != 200:
                return False
            return bool(resp.json().get("related"))
    except Exception as exc:  # noqa: BLE001
        log.debug("topology_related_failed", error=str(exc))
        return False


async def ingest_alertmanager_payload(session: AsyncSession, payload: dict) -> Incident:
    """Group alerts into an open incident within the correlation window."""
    alerts = payload.get("alerts") or []
    if not alerts:
        raise ValueError("no alerts in payload")

    fingerprints = sorted({_fingerprint(a) for a in alerts})
    primary = alerts[0]
    labels = {**(payload.get("commonLabels") or {}), **(primary.get("labels") or {})}
    namespace = labels.get("namespace")
    workload = _workload(primary)
    title = (
        (payload.get("commonAnnotations") or {}).get("summary")
        or (primary.get("annotations") or {}).get("summary")
        or labels.get("alertname")
        or "Alertmanager incident"
    )
    severity = _severity_from_alert(primary)
    window_start = datetime.now(UTC) - timedelta(seconds=settings.correlation_time_window_seconds)

    # Find open incident sharing any fingerprint OR topology path in window
    result = await session.execute(
        select(Incident)
        .where(Incident.status == IncidentStatus.open)
        .where(Incident.created_at >= window_start)
        .order_by(Incident.created_at.desc())
    )
    for existing in result.scalars().all():
        existing_fps = set(existing.alert_fingerprints or [])
        same_fp = bool(existing_fps.intersection(fingerprints))
        same_topo = False
        if not same_fp and workload and existing.workload:
            same_topo = await _topology_related(
                namespace,
                workload,
                existing.namespace,
                existing.workload,
            )
        if same_fp or same_topo:
            merged = list(dict.fromkeys([*(existing.alert_fingerprints or []), *fingerprints]))
            if len(merged) > settings.correlation_max_alerts_per_incident:
                merged = merged[: settings.correlation_max_alerts_per_incident]
            existing.alert_fingerprints = merged
            existing.raw_alerts = [*(existing.raw_alerts or []), *alerts]
            existing.updated_at = datetime.now(UTC)
            if _severity_rank(severity) > _severity_rank(existing.severity):
                existing.severity = severity
            # Enrich title hint when topology-merged
            if same_topo and not same_fp and workload and existing.workload != workload:
                hint = f" (+{workload})"
                if hint not in (existing.title or "") and len(existing.title or "") < 450:
                    existing.title = f"{existing.title}{hint}"
            await session.commit()
            await session.refresh(existing)
            log.info(
                "incident_correlated",
                external_id=existing.external_id,
                fingerprints=merged,
                via="fingerprint" if same_fp else "topology",
            )
            return existing

    seq = uuid4().hex[:8].upper()
    incident = Incident(
        external_id=f"INC-{seq}",
        title=str(title)[:500],
        status=IncidentStatus.open,
        severity=severity,
        namespace=namespace,
        workload=workload,
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

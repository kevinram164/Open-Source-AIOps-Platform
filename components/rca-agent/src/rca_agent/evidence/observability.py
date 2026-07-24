"""Optional Prometheus / Coroot evidence (best-effort)."""

from __future__ import annotations

import structlog
import httpx

from rca_agent.config import settings

log = structlog.get_logger()


async def collect_prometheus_evidence(namespace: str | None) -> list[str]:
    lines: list[str] = []
    if not settings.prometheus_url or not namespace:
        return lines
    # Simple instant query — may fail if auth/TLS required (OpenShift)
    query = f'kube_pod_container_status_waiting_reason{{namespace="{namespace}"}}'
    url = settings.prometheus_url.rstrip("/") + "/api/v1/query"
    try:
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            resp = await client.get(url, params={"query": query})
            if resp.status_code != 200:
                lines.append(f"Prometheus query HTTP {resp.status_code}")
                return lines
            data = resp.json()
            results = data.get("data", {}).get("result", [])
            for series in results[:15]:
                metric = series.get("metric", {})
                lines.append(
                    "Prom waiting "
                    f"pod={metric.get('pod')} container={metric.get('container')} "
                    f"reason={metric.get('reason')}"
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("prometheus_evidence_failed", error=str(exc))
        lines.append(f"Prometheus evidence unavailable: {type(exc).__name__}")
    return lines


async def collect_coroot_evidence(namespace: str | None) -> list[str]:
    lines: list[str] = []
    if not settings.coroot_url or not namespace:
        return lines
    # Coroot CE API varies by version — health ping only for Phase 3 skeleton
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(settings.coroot_url.rstrip("/") + "/")
            lines.append(
                f"Coroot reachable ({resp.status_code}) for namespace hint={namespace}; "
                "detailed topology enrichment TBD"
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("coroot_evidence_failed", error=str(exc))
        lines.append(f"Coroot evidence unavailable: {type(exc).__name__}")
    return lines

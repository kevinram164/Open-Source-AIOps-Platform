"""Next Best Action — map RCA → pending remediation drafts."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from incident_api.config import settings

LOG = logging.getLogger(__name__)

_RESTART = re.compile(
    r"restart|rollout|crashloop|oomkilled|imagepull|backoff|pod\s+recreat",
    re.I,
)
_SCALE = re.compile(
    r"scale|replica|capacity|horizontal|hpa|increase\s+pods|add\s+instance",
    re.I,
)
_NODE = re.compile(
    r"node|notready|disk\s*pressure|memory\s*pressure|pid\s*pressure|drain|cordon",
    re.I,
)
_REPLICAS = re.compile(r"(\d+)\s*replica", re.I)


def _text_blob(rca: dict[str, Any]) -> str:
    parts = list(rca.get("recommended_actions") or [])
    if rca.get("recommended_runbook"):
        parts.append(str(rca["recommended_runbook"]))
    if rca.get("probable_root_cause"):
        parts.append(str(rca["probable_root_cause"]))
    parts.extend(rca.get("supporting_evidence") or [])
    return "\n".join(str(p) for p in parts)


def map_rca_to_drafts(
    *,
    incident_external_id: str,
    incident_namespace: str | None,
    incident_workload: str | None,
    rca: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build RemediationCreate payloads (status will be pending on create)."""
    ns = rca.get("affected_namespace") or incident_namespace
    target = rca.get("affected_service") or incident_workload
    drafts: list[dict[str, Any]] = []

    # Prefer structured suggestions from RCA (if present)
    for item in rca.get("suggested_actions") or []:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if not action:
            continue
        drafts.append(
            {
                "incident_id": incident_external_id,
                "action": action,
                "namespace": item.get("namespace") or ns or "default",
                "target": item.get("target") or target or "unknown",
                "parameters": item.get("parameters") or {},
                "reason": item.get("reason")
                or f"NBA from RCA ({rca.get('probable_root_cause', '')[:120]})",
                "requested_by": "nba",
            }
        )

    if drafts:
        return drafts[:3]

    blob = _text_blob(rca)
    if not blob.strip():
        return []

    reason = f"NBA heuristic: {rca.get('probable_root_cause', '')[:160]}"

    if _NODE.search(blob):
        drafts.append(
            {
                "incident_id": incident_external_id,
                "action": "ansible-runbook",
                "namespace": "aiops-automation",
                "target": "cluster",
                "parameters": {"playbook": "node-diagnostics"},
                "reason": reason,
                "requested_by": "nba",
            }
        )
    elif _SCALE.search(blob) and ns and target:
        replicas = 2
        m = _REPLICAS.search(blob)
        if m:
            replicas = max(1, min(10, int(m.group(1))))
        drafts.append(
            {
                "incident_id": incident_external_id,
                "action": "gitops-scale",
                "namespace": ns,
                "target": target,
                "parameters": {"replicas": replicas},
                "reason": reason,
                "requested_by": "nba",
            }
        )
    elif _RESTART.search(blob) and ns and target:
        drafts.append(
            {
                "incident_id": incident_external_id,
                "action": "restart-deployment",
                "namespace": ns,
                "target": target,
                "parameters": {},
                "reason": reason,
                "requested_by": "nba",
            }
        )

    return drafts[:3]


async def create_pending_remediations(drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """POST drafts to remediation-controller; never raise to caller."""
    if not drafts:
        return []
    if not settings.nba_enabled:
        LOG.info("NBA disabled — skip %s drafts", len(drafts))
        return []

    base = settings.remediation_controller_url.rstrip("/")
    created: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for body in drafts:
            try:
                resp = await client.post(f"{base}/api/v1/remediations", json=body)
                if resp.status_code >= 400:
                    LOG.warning(
                        "NBA create failed action=%s status=%s body=%s",
                        body.get("action"),
                        resp.status_code,
                        resp.text[:200],
                    )
                    created.append(
                        {
                            "ok": False,
                            "action": body.get("action"),
                            "error": resp.text[:200],
                        }
                    )
                    continue
                data = resp.json()
                created.append(
                    {
                        "ok": True,
                        "id": data.get("id"),
                        "action": data.get("action"),
                        "status": data.get("status"),
                        "namespace": data.get("namespace"),
                        "target": data.get("target"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                LOG.warning("NBA create error: %s", exc)
                created.append({"ok": False, "action": body.get("action"), "error": str(exc)})
    return created

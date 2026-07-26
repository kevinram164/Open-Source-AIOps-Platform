"""Extra ops collectors for Phase 6 context pack (events, PVC, HPA)."""

from __future__ import annotations

from typing import Any

import structlog
from kubernetes import client, config
from kubernetes.client.rest import ApiException

log = structlog.get_logger()


def _core() -> client.CoreV1Api | None:
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        return client.CoreV1Api()
    except Exception as exc:  # noqa: BLE001
        log.warning("ops_extra_core_unavailable", error=str(exc))
        return None


def _autoscaling() -> client.AutoscalingV2Api | None:
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        return client.AutoscalingV2Api()
    except Exception as exc:  # noqa: BLE001
        log.warning("ops_extra_hpa_unavailable", error=str(exc))
        return None


def collect_recent_warnings(
    *,
    namespace: str | None = None,
    limit: int = 15,
) -> dict[str, Any]:
    """Recent Warning events (skip noisy Normal)."""
    out: dict[str, Any] = {"events": [], "warnings": []}
    api = _core()
    if not api:
        out["warnings"].append("core api unavailable")
        return out
    try:
        if namespace:
            items = api.list_namespaced_event(namespace).items
        else:
            items = api.list_event_for_all_namespaces().items
        ranked = sorted(
            items,
            key=lambda e: str(
                e.last_timestamp or e.event_time or e.metadata.creation_timestamp or ""
            ),
            reverse=True,
        )
        for ev in ranked:
            if (ev.type or "") != "Warning":
                continue
            ns = ev.metadata.namespace or namespace or ""
            if not namespace and ns and (ns.startswith("openshift-") or ns.startswith("kube-")):
                continue
            msg = (ev.message or "").replace("\n", " ").strip()
            if len(msg) > 240:
                msg = msg[:240] + "…"
            out["events"].append(
                {
                    "namespace": ns,
                    "object": f"{ev.involved_object.kind}/{ev.involved_object.name}",
                    "reason": ev.reason,
                    "message": msg,
                    "count": ev.count,
                }
            )
            if len(out["events"]) >= limit:
                break
    except ApiException as exc:
        out["warnings"].append(f"events: {exc.status} {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"events error: {exc}")
    return out


def collect_pvc_issues(*, namespace: str | None = None, limit: int = 20) -> dict[str, Any]:
    """PVCs that are Pending or not Bound."""
    out: dict[str, Any] = {"pvcs": [], "warnings": []}
    api = _core()
    if not api:
        out["warnings"].append("core api unavailable")
        return out
    try:
        if namespace:
            items = api.list_namespaced_persistent_volume_claim(namespace).items
        else:
            items = api.list_persistent_volume_claim_for_all_namespaces().items
        for pvc in items:
            ns = pvc.metadata.namespace
            if not namespace and ns and (ns.startswith("openshift-") or ns.startswith("kube-")):
                continue
            phase = (pvc.status.phase if pvc.status else None) or "Unknown"
            if phase == "Bound":
                continue
            out["pvcs"].append(
                {
                    "namespace": ns,
                    "name": pvc.metadata.name,
                    "phase": phase,
                    "storage_class": pvc.spec.storage_class_name,
                }
            )
            if len(out["pvcs"]) >= limit:
                break
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"pvc error: {exc}")
    return out


def collect_hpa_status(*, namespace: str | None = None, limit: int = 25) -> dict[str, Any]:
    """HPA current vs min/max — flag at max or unable to scale."""
    out: dict[str, Any] = {"hpas": [], "warnings": []}
    api = _autoscaling()
    if not api:
        out["warnings"].append("autoscaling api unavailable")
        return out
    try:
        if namespace:
            items = api.list_namespaced_horizontal_pod_autoscaler(namespace).items
        else:
            items = api.list_horizontal_pod_autoscaler_for_all_namespaces().items
        for h in items:
            ns = h.metadata.namespace
            if not namespace and ns and (ns.startswith("openshift-") or ns.startswith("kube-")):
                continue
            desired = h.status.desired_replicas
            current = h.status.current_replicas
            mx = h.spec.max_replicas
            mn = h.spec.min_replicas
            at_max = mx is not None and desired is not None and desired >= mx
            out["hpas"].append(
                {
                    "namespace": ns,
                    "name": h.metadata.name,
                    "min": mn,
                    "max": mx,
                    "current": current,
                    "desired": desired,
                    "at_max": bool(at_max),
                    "target": f"{h.spec.scale_target_ref.kind}/{h.spec.scale_target_ref.name}",
                }
            )
            if len(out["hpas"]) >= limit:
                break
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"hpa error: {exc}")
    return out

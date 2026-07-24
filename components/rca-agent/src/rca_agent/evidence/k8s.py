"""Collect Kubernetes evidence (read-only)."""

from __future__ import annotations

import structlog
from kubernetes import client, config
from kubernetes.client.rest import ApiException

log = structlog.get_logger()


def _load_api() -> client.CoreV1Api | None:
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        return client.CoreV1Api()
    except Exception as exc:  # noqa: BLE001
        log.warning("k8s_client_unavailable", error=str(exc))
        return None


def collect_k8s_evidence(namespace: str | None, workload: str | None, limit: int = 20) -> list[str]:
    """Return human-readable evidence lines from pods/events."""
    lines: list[str] = []
    api = _load_api()
    if not api or not namespace:
        if not namespace:
            lines.append("No namespace on incident — skipped Kubernetes evidence.")
        return lines

    try:
        pods = api.list_namespaced_pod(namespace)
        for pod in pods.items[:limit]:
            name = pod.metadata.name
            phase = pod.status.phase
            if workload and workload not in name:
                continue
            restarts = 0
            waiting = None
            if pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    restarts += cs.restart_count or 0
                    if cs.state and cs.state.waiting:
                        waiting = cs.state.waiting.reason
            lines.append(
                f"Pod {name}: phase={phase} restarts={restarts}"
                + (f" waiting={waiting}" if waiting else "")
            )
            if waiting in {"CrashLoopBackOff", "OOMKilled", "Error", "ImagePullBackOff"}:
                lines.append(f"Problematic container state on {name}: {waiting}")
    except ApiException as exc:
        lines.append(f"Kubernetes pods list failed: {exc.status} {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Kubernetes pods error: {exc}")

    try:
        events = api.list_namespaced_event(namespace)
        # newest first
        items = sorted(
            events.items,
            key=lambda e: str(
                e.last_timestamp or e.event_time or e.metadata.creation_timestamp or ""
            ),
            reverse=True,
        )
        for ev in items[:limit]:
            if workload and workload not in (ev.involved_object.name or ""):
                # keep Warning events broadly
                if ev.type != "Warning":
                    continue
            msg = (ev.message or "").replace("\n", " ")[:200]
            lines.append(
                f"Event {ev.type} {ev.reason} on {ev.involved_object.kind}/{ev.involved_object.name}: {msg}"
            )
    except ApiException as exc:
        lines.append(f"Kubernetes events list failed: {exc.status} {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Kubernetes events error: {exc}")

    return lines[:50]

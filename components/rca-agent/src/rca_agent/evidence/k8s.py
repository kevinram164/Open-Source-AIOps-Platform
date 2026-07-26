"""Collect Kubernetes evidence (read-only) — investigator-grade."""

from __future__ import annotations

from collections import Counter
from typing import Any

import structlog
from kubernetes import client, config
from kubernetes.client.rest import ApiException

log = structlog.get_logger()

IMAGE_PULL = {"ImagePullBackOff", "ErrImagePull", "InvalidImageName"}
CRASH = {"CrashLoopBackOff", "Error", "RunContainerError"}
OOM = {"OOMKilled"}


def _load_core() -> client.CoreV1Api | None:
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        return client.CoreV1Api()
    except Exception as exc:  # noqa: BLE001
        log.warning("k8s_client_unavailable", error=str(exc))
        return None


def _load_apps() -> client.AppsV1Api | None:
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        return client.AppsV1Api()
    except Exception as exc:  # noqa: BLE001
        log.warning("k8s_apps_unavailable", error=str(exc))
        return None


def _container_waiting(cs: Any) -> tuple[str | None, str | None]:
    if not cs.state or not cs.state.waiting:
        return None, None
    w = cs.state.waiting
    return w.reason, (w.message or "").replace("\n", " ").strip() or None


def _container_terminated(cs: Any) -> tuple[str | None, str | None, int | None]:
    if not cs.last_state or not cs.last_state.terminated:
        return None, None, None
    t = cs.last_state.terminated
    return t.reason, (t.message or "").replace("\n", " ").strip() or None, t.exit_code


def collect_k8s_evidence(namespace: str | None, workload: str | None, limit: int = 40) -> list[str]:
    """Human-readable evidence lines including waiting.message and full Warning events."""
    lines: list[str] = []
    api = _load_core()
    if not api or not namespace:
        if not namespace:
            lines.append("No namespace on incident — skipped Kubernetes evidence.")
        return lines

    subtype_hits: Counter[str] = Counter()

    try:
        pods = api.list_namespaced_pod(namespace)
        matched = 0
        for pod in pods.items:
            name = pod.metadata.name or ""
            if workload and workload not in name:
                continue
            matched += 1
            if matched > limit:
                break
            phase = pod.status.phase
            restarts = 0
            details: list[str] = []
            if pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    restarts += cs.restart_count or 0
                    reason, message = _container_waiting(cs)
                    if reason:
                        details.append(f"waiting.reason={reason}")
                        subtype_hits[reason] += 1
                        if message:
                            details.append(f"waiting.message={message[:400]}")
                    term_r, term_m, exit_code = _container_terminated(cs)
                    if term_r:
                        details.append(f"lastTerminated.reason={term_r}")
                        subtype_hits[term_r] += 1
                        if exit_code is not None:
                            details.append(f"lastTerminated.exitCode={exit_code}")
                        if term_m:
                            details.append(f"lastTerminated.message={term_m[:300]}")
            line = f"Pod {name}: phase={phase} restarts={restarts}"
            if details:
                line += " | " + "; ".join(details)
            lines.append(line)
        if workload and matched == 0:
            lines.append(f"No pods matched workload filter '{workload}' in namespace {namespace}.")
    except ApiException as exc:
        lines.append(f"Kubernetes pods list failed: {exc.status} {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Kubernetes pods error: {exc}")

    try:
        events = api.list_namespaced_event(namespace)
        items = sorted(
            events.items,
            key=lambda e: str(
                e.last_timestamp or e.event_time or e.metadata.creation_timestamp or ""
            ),
            reverse=True,
        )
        added = 0
        warn_extra = 0
        for ev in items:
            obj_name = ev.involved_object.name or ""
            matched_wl = bool(workload) and workload in obj_name
            if workload and not matched_wl:
                # still keep a few namespace-wide Warning events
                if ev.type != "Warning" or warn_extra >= 8:
                    continue
                warn_extra += 1
            msg = (ev.message or "").replace("\n", " ").strip()
            if len(msg) > 500:
                msg = msg[:500] + "…"
            lines.append(
                f"Event type={ev.type} reason={ev.reason} "
                f"object={ev.involved_object.kind}/{obj_name}: {msg}"
            )
            added += 1
            if added >= limit:
                break
    except ApiException as exc:
        lines.append(f"Kubernetes events list failed: {exc.status} {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Kubernetes events error: {exc}")

    if subtype_hits:
        top = ", ".join(f"{k}×{v}" for k, v in subtype_hits.most_common(5))
        lines.insert(0, f"ErrorSubtypeHistogram: {top}")

    return lines[:80]


def collect_ops_snapshot(
    *,
    namespace: str | None = None,
    focus: str | None = None,
) -> dict[str, Any]:
    """Live cluster ops snapshot for investigator Q&A (not tied to one incident)."""
    api = _load_core()
    out: dict[str, Any] = {
        "nodes": [],
        "crashloop_pods": [],
        "imagepull_pods": [],
        "oom_pods": [],
        "not_ready_pods": [],
        "warnings": [],
        "namespace_filter": namespace,
        "focus": focus,
    }
    if not api:
        out["warnings"].append("Kubernetes client unavailable")
        return out

    try:
        for node in api.list_node().items:
            name = node.metadata.name
            ready = "Unknown"
            disk_pressure = "Unknown"
            memory_pressure = "Unknown"
            pid_pressure = "Unknown"
            for cond in node.status.conditions or []:
                if cond.type == "Ready":
                    ready = cond.status
                elif cond.type == "DiskPressure":
                    disk_pressure = cond.status
                elif cond.type == "MemoryPressure":
                    memory_pressure = cond.status
                elif cond.type == "PIDPressure":
                    pid_pressure = cond.status
            allocatable = node.status.allocatable or {}
            out["nodes"].append(
                {
                    "name": name,
                    "ready": ready,
                    "disk_pressure": disk_pressure,
                    "memory_pressure": memory_pressure,
                    "pid_pressure": pid_pressure,
                    "cpu_allocatable": allocatable.get("cpu"),
                    "memory_allocatable": allocatable.get("memory"),
                    "ephemeral_storage_allocatable": allocatable.get("ephemeral-storage"),
                }
            )
            if ready != "True":
                out["warnings"].append(f"Node {name} Ready={ready}")
            if disk_pressure == "True":
                out["warnings"].append(f"Node {name} DiskPressure=True")
            if memory_pressure == "True":
                out["warnings"].append(f"Node {name} MemoryPressure=True")
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"list nodes failed: {exc}")

    try:
        if namespace:
            pod_lists = [api.list_namespaced_pod(namespace)]
        else:
            pod_lists = [api.list_pod_for_all_namespaces()]
        for plist in pod_lists:
            for pod in plist.items:
                ns = pod.metadata.namespace
                name = pod.metadata.name
                # skip system noise for cluster-wide unless focused
                if not namespace and ns and (
                    ns.startswith("openshift-") or ns.startswith("kube-")
                ):
                    continue
                phase = pod.status.phase
                if phase not in {"Running", "Succeeded"} and phase:
                    out["not_ready_pods"].append({"namespace": ns, "name": name, "phase": phase})
                if not pod.status.container_statuses:
                    continue
                for cs in pod.status.container_statuses:
                    reason, message = _container_waiting(cs)
                    term_r, _, _ = _container_terminated(cs)
                    entry = {
                        "namespace": ns,
                        "name": name,
                        "container": cs.name,
                        "reason": reason or term_r,
                        "message": (message or "")[:300],
                        "restarts": cs.restart_count or 0,
                    }
                    r = reason or term_r
                    if r in IMAGE_PULL:
                        out["imagepull_pods"].append(entry)
                    elif r in CRASH or (cs.restart_count or 0) >= 3 and reason == "CrashLoopBackOff":
                        out["crashloop_pods"].append(entry)
                    elif r in OOM or term_r in OOM:
                        out["oom_pods"].append(entry)
                    elif reason == "CrashLoopBackOff":
                        out["crashloop_pods"].append(entry)
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"list pods failed: {exc}")

    # trim
    for key in ("crashloop_pods", "imagepull_pods", "oom_pods", "not_ready_pods", "nodes"):
        out[key] = out[key][:40]
    return out


def resolve_deployment_for_pod(namespace: str, pod_name: str) -> str | None:
    """Best-effort map pod → deployment name for restart remediation."""
    apps = _load_apps()
    core = _load_core()
    if not apps or not core:
        return None
    try:
        pod = core.read_namespaced_pod(pod_name, namespace)
        # owner RS → deployment
        for ref in pod.metadata.owner_references or []:
            if ref.kind == "ReplicaSet":
                rs = apps.read_namespaced_replica_set(ref.name, namespace)
                for oref in rs.metadata.owner_references or []:
                    if oref.kind == "Deployment":
                        return oref.name
        # fallback: strip hash suffix
        parts = pod_name.rsplit("-", 2)
        if len(parts) >= 3:
            return "-".join(parts[:-2])
    except Exception as exc:  # noqa: BLE001
        log.warning("resolve_deployment_failed", error=str(exc))
    return None

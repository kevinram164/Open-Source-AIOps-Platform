"""Live resource usage via metrics.k8s.io + optional Prometheus."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import structlog
from kubernetes import client, config
from kubernetes.client.rest import ApiException

from rca_agent.config import settings
from rca_agent.evidence.pvc_du import collect_pvc_usage_via_du

log = structlog.get_logger()


def _load_custom() -> client.CustomObjectsApi | None:
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        return client.CustomObjectsApi()
    except Exception as exc:  # noqa: BLE001
        log.warning("metrics_api_unavailable", error=str(exc))
        return None


def _parse_cpu(value: str | None) -> float:
    """Return CPU cores as float."""
    if not value:
        return 0.0
    v = value.strip()
    if v.endswith("n"):
        return int(v[:-1]) / 1_000_000_000
    if v.endswith("u"):
        return int(v[:-1]) / 1_000_000
    if v.endswith("m"):
        return int(v[:-1]) / 1000
    return float(v)


def _parse_mem_bytes(value: str | None) -> float:
    if not value:
        return 0.0
    v = value.strip()
    units = {
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
    }
    for suf, mul in units.items():
        if v.endswith(suf):
            return float(v[: -len(suf)]) * mul
    if v.endswith("i"):
        return float(v[:-1])
    return float(v)


def _fmt_cpu(cores: float) -> str:
    if cores < 0.001:
        return f"{cores * 1000:.2f}m"
    if cores < 1:
        return f"{cores * 1000:.0f}m"
    return f"{cores:.2f}"


def _fmt_mem(nbytes: float) -> str:
    if nbytes >= 1024**3:
        return f"{nbytes / 1024**3:.2f}Gi"
    if nbytes >= 1024**2:
        return f"{nbytes / 1024**2:.0f}Mi"
    return f"{nbytes / 1024:.0f}Ki"


def collect_pod_metrics(
    *,
    namespace: str | None = None,
    top_n: int = 15,
) -> dict[str, Any]:
    """Top pods by CPU / memory from metrics.k8s.io."""
    out: dict[str, Any] = {
        "source": "metrics.k8s.io",
        "top_cpu_pods": [],
        "top_memory_pods": [],
        "warnings": [],
    }
    api = _load_custom()
    if not api:
        out["warnings"].append("metrics.k8s.io client unavailable")
        return out

    try:
        if namespace:
            data = api.list_namespaced_custom_object(
                "metrics.k8s.io", "v1beta1", namespace, "pods"
            )
        else:
            data = api.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "pods")
    except ApiException as exc:
        out["warnings"].append(f"metrics.k8s.io pods: {exc.status} {exc.reason}")
        return out
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"metrics.k8s.io pods error: {exc}")
        return out

    rows: list[dict[str, Any]] = []
    for item in data.get("items") or []:
        meta = item.get("metadata") or {}
        ns = meta.get("namespace") or namespace or ""
        name = meta.get("name") or ""
        if not namespace and (ns.startswith("openshift-") or ns.startswith("kube-")):
            continue
        cpu = 0.0
        mem = 0.0
        for c in item.get("containers") or []:
            usage = c.get("usage") or {}
            cpu += _parse_cpu(usage.get("cpu"))
            mem += _parse_mem_bytes(usage.get("memory"))
        rows.append(
            {
                "namespace": ns,
                "name": name,
                "cpu_cores": round(cpu, 4),
                "cpu": _fmt_cpu(cpu),
                "memory_bytes": int(mem),
                "memory": _fmt_mem(mem),
            }
        )

    by_cpu = sorted(rows, key=lambda r: r["cpu_cores"], reverse=True)[:top_n]
    by_mem = sorted(rows, key=lambda r: r["memory_bytes"], reverse=True)[:top_n]
    out["top_cpu_pods"] = by_cpu
    out["top_memory_pods"] = by_mem
    return out


def collect_node_metrics(*, top_n: int = 20) -> dict[str, Any]:
    out: dict[str, Any] = {
        "source": "metrics.k8s.io",
        "nodes": [],
        "warnings": [],
    }
    api = _load_custom()
    if not api:
        out["warnings"].append("metrics.k8s.io client unavailable")
        return out
    try:
        data = api.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "nodes")
    except ApiException as exc:
        out["warnings"].append(f"metrics.k8s.io nodes: {exc.status} {exc.reason}")
        return out
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"metrics.k8s.io nodes error: {exc}")
        return out

    rows = []
    for item in data.get("items") or []:
        name = (item.get("metadata") or {}).get("name")
        usage = item.get("usage") or {}
        cpu = _parse_cpu(usage.get("cpu"))
        mem = _parse_mem_bytes(usage.get("memory"))
        rows.append(
            {
                "name": name,
                "cpu_cores": round(cpu, 4),
                "cpu": _fmt_cpu(cpu),
                "memory_bytes": int(mem),
                "memory": _fmt_mem(mem),
            }
        )
    out["nodes"] = sorted(rows, key=lambda r: r["cpu_cores"], reverse=True)[:top_n]
    return out


def _sa_token() -> str | None:
    path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return os.environ.get("PROMETHEUS_BEARER_TOKEN")


async def query_prometheus(promql: str) -> list[dict[str, Any]]:
    """Best-effort instant query against thanos/prometheus."""
    if not settings.prometheus_url:
        return []
    url = settings.prometheus_url.rstrip("/") + "/api/v1/query"
    headers: dict[str, str] = {}
    token = _sa_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            resp = await client.get(url, params={"query": promql}, headers=headers)
            if resp.status_code >= 400:
                log.warning("prometheus_query_http", status=resp.status_code, body=resp.text[:200])
                return []
            data = resp.json().get("data", {}).get("result", [])
            return data if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001
        log.warning("prometheus_query_failed", error=str(exc))
        return []


async def collect_prom_top_pods(
    *,
    namespace: str | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """Top pods by CPU/memory rate from Prometheus (if reachable)."""
    ns_filter = f',namespace="{namespace}"' if namespace else ""
    cpu_q = (
        f"topk({top_n}, sum by (namespace, pod) "
        f"(rate(container_cpu_usage_seconds_total{{container!=\"\",container!=\"POD\"{ns_filter}}}[5m])))"
    )
    mem_q = (
        f"topk({top_n}, sum by (namespace, pod) "
        f"(container_memory_working_set_bytes{{container!=\"\",container!=\"POD\"{ns_filter}}}))"
    )
    out: dict[str, Any] = {"source": "prometheus", "top_cpu_pods": [], "top_memory_pods": [], "warnings": []}
    cpu_rows = await query_prometheus(cpu_q)
    mem_rows = await query_prometheus(mem_q)
    for series in cpu_rows:
        m = series.get("metric") or {}
        val = float((series.get("value") or [0, 0])[1])
        out["top_cpu_pods"].append(
            {
                "namespace": m.get("namespace"),
                "name": m.get("pod"),
                "cpu_cores": round(val, 4),
                "cpu": _fmt_cpu(val),
            }
        )
    for series in mem_rows:
        m = series.get("metric") or {}
        val = float((series.get("value") or [0, 0])[1])
        out["top_memory_pods"].append(
            {
                "namespace": m.get("namespace"),
                "name": m.get("pod"),
                "memory_bytes": int(val),
                "memory": _fmt_mem(val),
            }
        )
    if not cpu_rows and not mem_rows:
        out["warnings"].append("Prometheus top-pod queries returned empty (auth or metric absent)")
    return out


async def collect_disk_metrics(
    *,
    namespace: str | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """Node root filesystem % used + PVC volume usage % (Prometheus)."""
    out: dict[str, Any] = {
        "source": "prometheus",
        "node_filesystem": [],
        "pvc_usage": [],
        "warnings": [],
    }
    # MUST sum by identity labels — bare A/B matches on all shared labels and
    # often yields the same bogus % for every series (e.g. all PVCs = 16.6%).
    node_q = (
        f"topk({top_n}, "
        "100 * (1 - ("
        'sum by (instance, mountpoint) (node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay|nsfs"})'
        " / "
        'sum by (instance, mountpoint) (node_filesystem_size_bytes{mountpoint="/",fstype!~"tmpfs|overlay|nsfs"})'
        ")))"
    )
    ns_filter = f'namespace="{namespace}"' if namespace else ""
    pvc_sel = "{" + ns_filter + "}" if ns_filter else ""
    pvc_q = (
        f"topk({top_n}, "
        "100 * ("
        f"sum by (namespace, persistentvolumeclaim) (kubelet_volume_stats_used_bytes{pvc_sel})"
        " / "
        f"sum by (namespace, persistentvolumeclaim) (kubelet_volume_stats_capacity_bytes{pvc_sel})"
        "))"
    )

    node_rows = await query_prometheus(node_q)
    pvc_rows = await query_prometheus(pvc_q)

    for series in node_rows:
        m = series.get("metric") or {}
        val = float((series.get("value") or [0, 0])[1])
        node = m.get("instance") or m.get("node") or m.get("nodename") or "unknown"
        out["node_filesystem"].append(
            {
                "node": node,
                "mountpoint": m.get("mountpoint") or "/",
                "used_percent": round(val, 1),
            }
        )

    for series in pvc_rows:
        m = series.get("metric") or {}
        try:
            val = float((series.get("value") or [0, 0])[1])
        except (TypeError, ValueError):
            continue
        if val != val:  # NaN
            continue
        pvc_name = m.get("persistentvolumeclaim") or m.get("pvc")
        if not pvc_name:
            continue
        out["pvc_usage"].append(
            {
                "namespace": m.get("namespace"),
                "persistentvolumeclaim": pvc_name,
                "used_percent": round(val, 1),
            }
        )

    # Absolute bytes (detect shared-FS metrics: same % for every PVC)
    pvc_used_q = (
        f"topk({top_n * 2}, "
        f"sum by (namespace, persistentvolumeclaim) (kubelet_volume_stats_used_bytes{pvc_sel}))"
    )
    pvc_cap_q = (
        f"sum by (namespace, persistentvolumeclaim) (kubelet_volume_stats_capacity_bytes{pvc_sel})"
    )
    used_map: dict[tuple[str, str], float] = {}
    cap_map: dict[tuple[str, str], float] = {}
    for series in await query_prometheus(pvc_used_q):
        m = series.get("metric") or {}
        key = (str(m.get("namespace") or ""), str(m.get("persistentvolumeclaim") or ""))
        if key[1]:
            used_map[key] = float((series.get("value") or [0, 0])[1])
    for series in await query_prometheus(pvc_cap_q):
        m = series.get("metric") or {}
        key = (str(m.get("namespace") or ""), str(m.get("persistentvolumeclaim") or ""))
        if key[1]:
            cap_map[key] = float((series.get("value") or [0, 0])[1])
    for row in out["pvc_usage"]:
        key = (str(row.get("namespace") or ""), str(row.get("persistentvolumeclaim") or ""))
        ub, cb = used_map.get(key), cap_map.get(key)
        if ub is not None:
            row["used_bytes"] = int(ub)
            row["used_human"] = _fmt_mem(ub)
        if cb is not None:
            row["capacity_bytes"] = int(cb)
            row["capacity_human"] = _fmt_mem(cb)

    # Deduplicate identical % smell for operators (shared NFS/CSI often looks like this)
    pcts = [p["used_percent"] for p in out["pvc_usage"]]
    shared_fs = len(pcts) >= 3 and max(pcts) - min(pcts) < 0.5
    if shared_fs:
        caps = {p.get("capacity_bytes") for p in out["pvc_usage"] if p.get("capacity_bytes")}
        out["warnings"].append(
            "PVC used% nearly identical for all claims — kubelet stats often reflect "
            "shared filesystem (NFS/CSI) fill, not per-PVC directory usage. "
            "Falling back to du vs claim request when possible."
            + (f" distinct_capacities={len(caps)}." if caps else "")
        )

    # Per-PVC directory usage (works on NFS where kubelet % is share-wide)
    try:
        du = await asyncio.to_thread(
            collect_pvc_usage_via_du,
            namespace=namespace,
            # Cluster-wide: keep small so ops/context stays under deadline
            max_pvcs=8 if namespace else 6,
            workers=3,
        )
        out["warnings"].extend(du.get("warnings") or [])
        du_rows = [
            r
            for r in (du.get("pvc_usage") or [])
            if isinstance(r, dict) and r.get("used_percent") is not None
        ]
        if du_rows:
            out["pvc_usage_prom"] = out["pvc_usage"]  # keep share-wide for compare
            out["pvc_usage"] = du_rows[:top_n]
            out["pvc_usage_method"] = "du"
        elif shared_fs:
            out["warnings"].append(
                "du per-PVC unavailable — keep treating kubelet % as share fill only"
            )
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"pvc du: {exc}")

    if not node_rows and not out["pvc_usage"]:
        out["warnings"].append(
            "Prometheus disk queries empty — need cluster-monitoring-view + node-exporter metrics"
        )
    return out


def collect_workload_inventory(namespace: str | None = None) -> dict[str, Any]:
    """Deployments / StatefulSets summary for ops Q&A."""
    out: dict[str, Any] = {"deployments": [], "statefulsets": [], "warnings": []}
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        apps = client.AppsV1Api()
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(str(exc))
        return out

    try:
        if namespace:
            deps = apps.list_namespaced_deployment(namespace).items
            sts = apps.list_namespaced_stateful_set(namespace).items
        else:
            deps = apps.list_deployment_for_all_namespaces().items
            sts = apps.list_stateful_set_for_all_namespaces().items
        for d in deps:
            ns = d.metadata.namespace
            if not namespace and ns and (ns.startswith("openshift-") or ns.startswith("kube-")):
                continue
            out["deployments"].append(
                {
                    "namespace": ns,
                    "name": d.metadata.name,
                    "ready": f"{d.status.ready_replicas or 0}/{d.spec.replicas or 0}",
                    "replicas": d.spec.replicas or 0,
                    "ready_replicas": d.status.ready_replicas or 0,
                }
            )
        for s in sts:
            ns = s.metadata.namespace
            if not namespace and ns and (ns.startswith("openshift-") or ns.startswith("kube-")):
                continue
            out["statefulsets"].append(
                {
                    "namespace": ns,
                    "name": s.metadata.name,
                    "ready": f"{s.status.ready_replicas or 0}/{s.spec.replicas or 0}",
                    "replicas": s.spec.replicas or 0,
                }
            )
        out["deployments"] = out["deployments"][:40]
        out["statefulsets"] = out["statefulsets"][:20]
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"inventory failed: {exc}")
    return out

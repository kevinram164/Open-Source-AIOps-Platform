"""Ops context endpoints — one multi-facet pack for any operator question."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from rca_agent.evidence.k8s import collect_ops_snapshot, resolve_deployment_for_pod
from rca_agent.evidence.ops_extra import (
    collect_hpa_status,
    collect_pvc_issues,
    collect_recent_warnings,
)
from rca_agent.evidence.ops_metrics import (
    collect_disk_metrics,
    collect_node_metrics,
    collect_pod_metrics,
    collect_prom_top_pods,
    collect_workload_inventory,
)
from rca_agent.evidence.pvc_du import collect_pvc_usage_via_du

router = APIRouter(prefix="/api/v1")

# Full pack must finish under chat client timeout (~50–60s) + browser ~120s wall
_OPS_CONTEXT_DEADLINE_S = 55.0
# Cluster-wide PVC du alone often needs ~25–40s; give headroom without Prom/K8s pack
_OPS_PVC_DEADLINE_S = 70.0

_PVC_DISK_RE = re.compile(
    r"\b(pvc|persistentvolumeclaim|disk|filesystem|storage|volume)\b|"
    r"(ổ\s*cứng|dung\s*lượng|ổ\s*đĩa)",
    re.IGNORECASE,
)


class OpsSnapshotRequest(BaseModel):
    namespace: str | None = None
    focus: str | None = None


class OpsContextRequest(BaseModel):
    """Always returns a bounded platform context pack (not topic-gated)."""

    question: str | None = Field(default=None, description="Optional; stored for tracing only")
    namespace: str | None = None


class ResolvePodRequest(BaseModel):
    namespace: str
    pod_name: str


def is_pvc_disk_question(question: str | None) -> bool:
    return bool(question and _PVC_DISK_RE.search(question))


async def _run(sync_fn, *args, **kwargs):
    return await asyncio.to_thread(sync_fn, *args, **kwargs)


async def build_pvc_context(namespace: str | None = None) -> dict[str, Any]:
    """PVC-only pack: du vs claim request — skips Prom + other collectors."""
    warnings: list[str] = []
    evidence: list[str] = []
    try:
        du = await asyncio.wait_for(
            asyncio.to_thread(
                collect_pvc_usage_via_du,
                namespace=namespace,
                max_pvcs=12 if not namespace else 10,
                workers=3,
            ),
            timeout=_OPS_PVC_DEADLINE_S,
        )
    except asyncio.TimeoutError:
        return {
            "namespace": namespace,
            "summary": {
                "scope": namespace or "cluster",
                "metrics_source": "timeout",
                "counts": {},
                "highlights": [
                    f"PVC du timed out after {_OPS_PVC_DEADLINE_S:.0f}s"
                ],
            },
            "facts": {"disk": {"pvc_usage": [], "pvc_usage_method": "du"}},
            "evidence": [f"ops_pvc_timeout_{int(_OPS_PVC_DEADLINE_S)}s"],
            "warnings": [f"build_pvc_context exceeded {_OPS_PVC_DEADLINE_S}s"],
        }

    warnings.extend(du.get("warnings") or [])
    pvc_usage = [
        r
        for r in (du.get("pvc_usage") or [])
        if isinstance(r, dict) and r.get("used_percent") is not None
    ]
    for p in pvc_usage[:12]:
        evidence.append(
            f"PVCUsage {p.get('namespace')}/{p.get('persistentvolumeclaim')}: "
            f"used={p.get('used_percent')}% "
            f"({p.get('used_human') or '?'}/{p.get('capacity_human') or '?'} claim) "
            f"via=du"
        )
    hot = [p for p in pvc_usage if (p.get("used_percent") or 0) >= 80]
    summary = {
        "scope": namespace or "cluster (non-system namespaces)",
        "metrics_source": "du",
        "counts": {"pvc_hot": len(hot), "pvc_measured": len(pvc_usage)},
        "highlights": (
            [f"{len(hot)} PVC(s) ≥80% used (du vs claim)"]
            if hot
            else [f"{len(pvc_usage)} PVC(s) measured via du — none ≥80%"]
            if pvc_usage
            else ["No PVC usage measured via du"]
        ),
    }
    return {
        "namespace": namespace,
        "summary": summary,
        "facts": {
            "metrics_source": "du",
            "disk": {
                "node_filesystem": [],
                "pvc_usage": pvc_usage[:15],
                "pvc_usage_method": "du",
                "nodes_disk_pressure": [],
            },
        },
        "evidence": evidence[:40],
        "warnings": warnings[:20],
    }


async def build_platform_context(
    namespace: str | None = None, *, question: str | None = None
) -> dict[str, Any]:
    """
    Collect a general-purpose ops fact pack so chat can answer *many* questions
    without hardcoding one topic per release.

    PVC/disk questions use a lighter du-only path (avoids full-pack timeout).
    """
    if is_pvc_disk_question(question):
        return await build_pvc_context(namespace=namespace)

    try:
        return await asyncio.wait_for(
            _build_platform_context_inner(namespace),
            timeout=_OPS_CONTEXT_DEADLINE_S,
        )
    except asyncio.TimeoutError:
        return {
            "namespace": namespace,
            "summary": {
                "scope": namespace or "cluster",
                "metrics_source": "timeout",
                "counts": {},
                "highlights": [
                    f"ops context timed out after {_OPS_CONTEXT_DEADLINE_S:.0f}s — partial/empty facts"
                ],
            },
            "facts": {},
            "evidence": [f"ops_context_timeout_{int(_OPS_CONTEXT_DEADLINE_S)}s"],
            "warnings": [f"build_platform_context exceeded {_OPS_CONTEXT_DEADLINE_S}s"],
        }


async def _build_platform_context_inner(namespace: str | None = None) -> dict[str, Any]:
    warnings: list[str] = []
    evidence: list[str] = []

    # Parallel collect (sync K8s clients in threads; Prom already async)
    snap_t = _run(collect_ops_snapshot, namespace=namespace, focus=None)
    pod_t = _run(collect_pod_metrics, namespace=namespace)
    node_t = _run(collect_node_metrics)
    prom_t = collect_prom_top_pods(namespace=namespace)
    disk_t = collect_disk_metrics(namespace=namespace)
    inv_t = _run(collect_workload_inventory, namespace)
    ev_t = _run(collect_recent_warnings, namespace=namespace)
    pvc_t = _run(collect_pvc_issues, namespace=namespace)
    hpa_t = _run(collect_hpa_status, namespace=namespace)

    snap, pod_m, node_m, prom, disk, inv, ev, pvc, hpa = await asyncio.gather(
        snap_t, pod_t, node_t, prom_t, disk_t, inv_t, ev_t, pvc_t, hpa_t,
        return_exceptions=True,
    )

    def _ok(val, label: str):
        if isinstance(val, Exception):
            warnings.append(f"{label}: {val}")
            return {}
        return val or {}

    snap = _ok(snap, "ops_snapshot")
    pod_m = _ok(pod_m, "pod_metrics")
    node_m = _ok(node_m, "node_metrics")
    prom = _ok(prom, "prom")
    disk = _ok(disk, "disk")
    inv = _ok(inv, "inventory")
    ev = _ok(ev, "events")
    pvc = _ok(pvc, "pvc")
    hpa = _ok(hpa, "hpa")

    crash = snap.get("crashloop_pods") or []
    imagepull = snap.get("imagepull_pods") or []
    oom = snap.get("oom_pods") or []
    not_ready = snap.get("not_ready_pods") or []
    nodes_ready = snap.get("nodes") or []
    warnings.extend(snap.get("warnings") or [])
    warnings.extend(pod_m.get("warnings") or [])
    warnings.extend(node_m.get("warnings") or [])
    warnings.extend(prom.get("warnings") or [])
    warnings.extend(disk.get("warnings") or [])
    warnings.extend(inv.get("warnings") or [])
    warnings.extend(ev.get("warnings") or [])
    warnings.extend(pvc.get("warnings") or [])
    warnings.extend(hpa.get("warnings") or [])

    top_cpu = prom.get("top_cpu_pods") or pod_m.get("top_cpu_pods") or []
    top_mem = prom.get("top_memory_pods") or pod_m.get("top_memory_pods") or []
    metrics_source = "prometheus" if prom.get("top_cpu_pods") else "metrics.k8s.io"
    node_usage = node_m.get("nodes") or []
    node_fs = disk.get("node_filesystem") or []
    pvc_usage = disk.get("pvc_usage") or []
    nodes_disk_pressure = [n for n in nodes_ready if n.get("disk_pressure") == "True"]
    recent_events = ev.get("events") or []
    pvc_issues = pvc.get("pvcs") or []
    hpas = hpa.get("hpas") or []
    hpas_at_max = [h for h in hpas if h.get("at_max")]

    for p in top_cpu[:8]:
        evidence.append(
            f"CPU {p.get('namespace')}/{p.get('name')}: {p.get('cpu')} ({p.get('cpu_cores')} cores)"
        )
    for p in top_mem[:5]:
        evidence.append(f"MEM {p.get('namespace')}/{p.get('name')}: {p.get('memory')}")
    for n in node_usage[:8]:
        evidence.append(f"NodeUsage {n.get('name')}: cpu={n.get('cpu')} mem={n.get('memory')}")
    for n in nodes_ready:
        if n.get("ready") != "True":
            evidence.append(f"NodeReady {n.get('name')}: Ready={n.get('ready')}")
    for p in crash[:6]:
        evidence.append(
            f"CrashLoop {p.get('namespace')}/{p.get('name')} "
            f"restarts={p.get('restarts')} {p.get('reason')}"
        )
    for p in imagepull[:4]:
        evidence.append(
            f"ImagePull {p.get('namespace')}/{p.get('name')}: {p.get('message') or p.get('reason')}"
        )
    for p in oom[:4]:
        evidence.append(f"OOM {p.get('namespace')}/{p.get('name')}")
    for d in (inv.get("deployments") or [])[:12]:
        evidence.append(f"Deploy {d.get('namespace')}/{d.get('name')} ready={d.get('ready')}")
    for e in recent_events[:8]:
        evidence.append(
            f"Event Warning {e.get('namespace')}/{e.get('object')} "
            f"{e.get('reason')}: {e.get('message')}"
        )
    for p in pvc_issues[:5]:
        evidence.append(
            f"PVC {p.get('namespace')}/{p.get('name')} phase={p.get('phase')} "
            f"sc={p.get('storage_class')}"
        )
    for h in hpas_at_max[:5]:
        evidence.append(
            f"HPA {h.get('namespace')}/{h.get('name')} at max "
            f"({h.get('desired')}/{h.get('max')}) target={h.get('target')}"
        )
    for n in nodes_disk_pressure[:8]:
        evidence.append(f"NodeDiskPressure {n.get('name')}: DiskPressure=True")
    for n in node_fs[:8]:
        evidence.append(
            f"NodeFS {n.get('node')} {n.get('mountpoint')}: used={n.get('used_percent')}%"
        )
    for p in pvc_usage[:8]:
        method = p.get("method") or "prom"
        evidence.append(
            f"PVCUsage {p.get('namespace')}/{p.get('persistentvolumeclaim')}: "
            f"used={p.get('used_percent')}% "
            f"({p.get('used_human') or '?'}/{p.get('capacity_human') or '?'} claim) "
            f"via={method}"
        )

    summary = {
        "scope": namespace or "cluster (non-system namespaces)",
        "metrics_source": metrics_source,
        "counts": {
            "crashloop": len(crash),
            "imagepull": len(imagepull),
            "oom": len(oom),
            "not_ready_pods": len(not_ready),
            "deployments": len(inv.get("deployments") or []),
            "nodes": len(nodes_ready) or len(node_usage),
            "warning_events": len(recent_events),
            "pvc_not_bound": len(pvc_issues),
            "hpa_at_max": len(hpas_at_max),
            "nodes_disk_pressure": len(nodes_disk_pressure),
            "node_fs_hot": len([x for x in node_fs if (x.get("used_percent") or 0) >= 80]),
            "pvc_hot": len([x for x in pvc_usage if (x.get("used_percent") or 0) >= 80]),
        },
        "highlights": _highlights(
            top_cpu,
            crash,
            imagepull,
            nodes_ready,
            node_usage,
            recent_events=recent_events,
            pvc_issues=pvc_issues,
            hpas_at_max=hpas_at_max,
            node_fs=node_fs,
            pvc_usage=pvc_usage,
            nodes_disk_pressure=nodes_disk_pressure,
        ),
    }

    return {
        "namespace": namespace,
        "summary": summary,
        "facts": {
            "metrics_source": metrics_source,
            "top_cpu_pods": top_cpu,
            "top_memory_pods": top_mem,
            "node_usage": node_usage,
            "nodes_ready": nodes_ready,
            "crashloop_pods": crash[:20],
            "imagepull_pods": imagepull[:20],
            "oom_pods": oom[:20],
            "not_ready_pods": not_ready[:20],
            "inventory": {
                "deployments": (inv.get("deployments") or [])[:30],
                "statefulsets": (inv.get("statefulsets") or [])[:15],
            },
            "recent_warnings": recent_events[:15],
            "pvc_issues": pvc_issues[:15],
            "hpas": hpas[:20],
            "disk": {
                "node_filesystem": node_fs[:15],
                "pvc_usage": pvc_usage[:15],
                "pvc_usage_method": disk.get("pvc_usage_method") or "prometheus",
                "nodes_disk_pressure": nodes_disk_pressure[:10],
            },
        },
        "evidence": evidence[:40],
        "warnings": warnings[:20],
    }


def _highlights(
    top_cpu,
    crash,
    imagepull,
    nodes_ready,
    node_usage,
    *,
    recent_events=None,
    pvc_issues=None,
    hpas_at_max=None,
    node_fs=None,
    pvc_usage=None,
    nodes_disk_pressure=None,
) -> list[str]:
    notes: list[str] = []
    if crash:
        notes.append(f"{len(crash)} CrashLoopBackOff pod(s)")
    if imagepull:
        notes.append(f"{len(imagepull)} ImagePull issue(s)")
    if top_cpu:
        p = top_cpu[0]
        notes.append(f"Highest CPU: {p.get('namespace')}/{p.get('name')} ({p.get('cpu')})")
    not_ready_nodes = [n for n in (nodes_ready or []) if n.get("ready") != "True"]
    if not_ready_nodes:
        notes.append(f"{len(not_ready_nodes)} node(s) not Ready")
    if nodes_disk_pressure:
        notes.append(f"{len(nodes_disk_pressure)} node(s) DiskPressure=True")
    hot_fs = [x for x in (node_fs or []) if (x.get("used_percent") or 0) >= 80]
    if hot_fs:
        notes.append(f"{len(hot_fs)} node filesystem(s) ≥80%")
    hot_pvc = [x for x in (pvc_usage or []) if (x.get("used_percent") or 0) >= 80]
    if hot_pvc:
        notes.append(f"{len(hot_pvc)} PVC(s) ≥80% used")
    if pvc_issues:
        notes.append(f"{len(pvc_issues)} PVC not Bound")
    if hpas_at_max:
        notes.append(f"{len(hpas_at_max)} HPA at max replicas")
    if recent_events:
        notes.append(f"{len(recent_events)} recent Warning event(s)")
    if not notes and node_usage:
        notes.append("Cluster metrics collected — no major failure signals in pack")
    return notes[:10]


@router.post("/ops/snapshot")
async def ops_snapshot(req: OpsSnapshotRequest) -> dict[str, Any]:
    return collect_ops_snapshot(namespace=req.namespace, focus=req.focus)


@router.post("/ops/context")
async def ops_context(req: OpsContextRequest) -> dict[str, Any]:
    data = await build_platform_context(namespace=req.namespace, question=req.question)
    if req.question:
        data["question"] = req.question
    return data


@router.post("/ops/pvc")
async def ops_pvc(req: OpsContextRequest) -> dict[str, Any]:
    """PVC usage only (du vs claim) — preferred by Chat for disk/PVC questions."""
    data = await build_pvc_context(namespace=req.namespace)
    if req.question:
        data["question"] = req.question
    return data


@router.post("/ops/query")
async def ops_query(req: OpsContextRequest) -> dict[str, Any]:
    """Alias of /ops/context — kept for backward compatibility."""
    return await ops_context(req)


@router.post("/ops/resolve-pod")
async def resolve_pod(req: ResolvePodRequest) -> dict[str, Any]:
    return resolve_deployment_for_pod(req.namespace, req.pod_name)

"""Ops context endpoints — one multi-facet pack for any operator question."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from rca_agent.evidence.k8s import collect_ops_snapshot, resolve_deployment_for_pod
from rca_agent.evidence.ops_metrics import (
    collect_node_metrics,
    collect_pod_metrics,
    collect_prom_top_pods,
    collect_workload_inventory,
)

router = APIRouter(prefix="/api/v1")


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


async def build_platform_context(namespace: str | None = None) -> dict[str, Any]:
    """
    Collect a general-purpose ops fact pack so chat can answer *many* questions
    without hardcoding one topic per release.
    """
    warnings: list[str] = []
    evidence: list[str] = []

    # Failures / Ready
    snap = collect_ops_snapshot(namespace=namespace, focus=None)
    crash = snap.get("crashloop_pods") or []
    imagepull = snap.get("imagepull_pods") or []
    oom = snap.get("oom_pods") or []
    not_ready = snap.get("not_ready_pods") or []
    nodes_ready = snap.get("nodes") or []
    warnings.extend(snap.get("warnings") or [])

    # Metrics
    pod_m = collect_pod_metrics(namespace=namespace)
    node_m = collect_node_metrics()
    prom = await collect_prom_top_pods(namespace=namespace)
    warnings.extend(pod_m.get("warnings") or [])
    warnings.extend(node_m.get("warnings") or [])
    warnings.extend(prom.get("warnings") or [])

    top_cpu = prom.get("top_cpu_pods") or pod_m.get("top_cpu_pods") or []
    top_mem = prom.get("top_memory_pods") or pod_m.get("top_memory_pods") or []
    metrics_source = "prometheus" if prom.get("top_cpu_pods") else "metrics.k8s.io"
    node_usage = node_m.get("nodes") or []

    # Inventory
    inv = collect_workload_inventory(namespace)
    warnings.extend(inv.get("warnings") or [])

    # Compact evidence lines (LLM + template fallback)
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
        },
        "highlights": _highlights(top_cpu, crash, imagepull, nodes_ready, node_usage),
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
        },
        "evidence": evidence[:50],
        "warnings": warnings,
    }


def _highlights(
    top_cpu: list,
    crash: list,
    imagepull: list,
    nodes_ready: list,
    node_usage: list,
) -> list[str]:
    notes: list[str] = []
    if top_cpu:
        p = top_cpu[0]
        notes.append(f"Top CPU: {p.get('namespace')}/{p.get('name')} ({p.get('cpu')})")
    if node_usage:
        n = node_usage[0]
        notes.append(f"Top node CPU: {n.get('name')} ({n.get('cpu')})")
    if crash:
        notes.append(f"{len(crash)} CrashLoopBackOff pod(s)")
    if imagepull:
        notes.append(f"{len(imagepull)} ImagePull pod(s)")
    for n in nodes_ready:
        if n.get("ready") != "True":
            notes.append(f"Node {n.get('name')} Ready={n.get('ready')}")
    if not notes:
        notes.append("No strong anomalies in scanned scope.")
    return notes


@router.post("/ops/context")
async def ops_context(req: OpsContextRequest) -> dict[str, Any]:
    """Multi-facet platform context for arbitrary ops questions."""
    ctx = await build_platform_context(req.namespace)
    ctx["question"] = req.question
    return ctx


@router.post("/ops/query")
async def ops_query(req: OpsContextRequest) -> dict[str, Any]:
    """Alias of /ops/context — kept for backward compatibility."""
    ctx = await build_platform_context(req.namespace)
    ctx["question"] = req.question
    ctx["topic"] = "platform"  # no longer topic-gated
    return ctx


@router.post("/ops/snapshot")
async def ops_snapshot(req: OpsSnapshotRequest) -> dict:
    """Legacy snapshot + metrics enrichment."""
    ctx = await build_platform_context(req.namespace)
    snap = collect_ops_snapshot(namespace=req.namespace, focus=req.focus)
    snap["noteworthy"] = ctx["summary"]["highlights"]
    snap["top_cpu_pods"] = ctx["facts"]["top_cpu_pods"]
    snap["top_memory_pods"] = ctx["facts"]["top_memory_pods"]
    snap["node_usage"] = ctx["facts"]["node_usage"]
    snap["inventory"] = ctx["facts"]["inventory"]
    snap["metrics_source"] = ctx["facts"]["metrics_source"]
    snap["metrics_warnings"] = ctx["warnings"]
    return snap


@router.post("/ops/resolve-deployment")
async def resolve_deployment(req: ResolvePodRequest) -> dict:
    dep = resolve_deployment_for_pod(req.namespace, req.pod_name)
    return {
        "namespace": req.namespace,
        "pod_name": req.pod_name,
        "deployment": dep,
    }

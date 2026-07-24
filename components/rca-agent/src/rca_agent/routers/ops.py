"""Ops snapshot endpoints for investigator Q&A."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from rca_agent.evidence.k8s import collect_ops_snapshot, resolve_deployment_for_pod

router = APIRouter(prefix="/api/v1")


class OpsSnapshotRequest(BaseModel):
    namespace: str | None = None
    focus: str | None = Field(
        default=None,
        description="Optional focus: crashloop|imagepull|nodes|oom|noteworthy",
    )


class ResolvePodRequest(BaseModel):
    namespace: str
    pod_name: str


@router.post("/ops/snapshot")
async def ops_snapshot(req: OpsSnapshotRequest) -> dict:
    snap = collect_ops_snapshot(namespace=req.namespace, focus=req.focus)
    snap["noteworthy"] = _noteworthy_summary(snap)
    return snap


@router.post("/ops/resolve-deployment")
async def resolve_deployment(req: ResolvePodRequest) -> dict:
    dep = resolve_deployment_for_pod(req.namespace, req.pod_name)
    return {
        "namespace": req.namespace,
        "pod_name": req.pod_name,
        "deployment": dep,
    }


def _noteworthy_summary(snap: dict) -> list[str]:
    notes: list[str] = []
    for n in snap.get("nodes") or []:
        if n.get("ready") != "True":
            notes.append(f"Node {n.get('name')} Ready={n.get('ready')}")
    for key, label in (
        ("crashloop_pods", "CrashLoopBackOff"),
        ("imagepull_pods", "ImagePull"),
        ("oom_pods", "OOMKilled"),
    ):
        items = snap.get(key) or []
        if items:
            notes.append(f"{len(items)} pod(s) with {label}")
            for p in items[:5]:
                notes.append(
                    f"  - {p.get('namespace')}/{p.get('name')} "
                    f"reason={p.get('reason')} restarts={p.get('restarts')}"
                )
    not_ready = snap.get("not_ready_pods") or []
    if not_ready:
        notes.append(f"{len(not_ready)} pod(s) not Running/Succeeded")
    notes.extend(snap.get("warnings") or [])
    if not notes:
        notes.append("No major pod failure signatures in scanned namespaces.")
    return notes

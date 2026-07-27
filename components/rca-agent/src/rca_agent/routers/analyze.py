"""Analyze endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from rca_agent.evidence.k8s import collect_k8s_evidence
from rca_agent.evidence.observability import collect_coroot_evidence, collect_prometheus_evidence
from rca_agent.openai_rca import synthesize_rca
from rca_agent.schemas.rca_output import AnalyzeRequest, RcaOutput
from rca_agent.topology.graph import get_topology_async, topology_evidence_lines

router = APIRouter(prefix="/api/v1")

_STORE: dict[str, RcaOutput] = {}


@router.post("/analyze", response_model=RcaOutput)
async def analyze(req: AnalyzeRequest) -> RcaOutput:
    evidence: list[str] = []
    evidence.extend(collect_k8s_evidence(req.namespace, req.workload))
    evidence.extend(await collect_prometheus_evidence(req.namespace))
    evidence.extend(await collect_coroot_evidence(req.namespace, req.workload))
    topo = await get_topology_async(req.namespace, req.workload, hops=2)
    evidence.extend(topology_evidence_lines(topo))
    for alert in req.raw_alerts[:10]:
        labels = alert.get("labels") or {}
        ann = alert.get("annotations") or {}
        evidence.append(
            f"Alert {labels.get('alertname')}: {ann.get('summary') or ann.get('description') or labels}"
        )

    result = await synthesize_rca(req, evidence, topology=topo)
    key = req.external_id or req.incident_id
    _STORE[key] = result
    _STORE[req.incident_id] = result
    return result


@router.get("/analysis/{incident_id}", response_model=RcaOutput)
async def get_analysis(incident_id: str) -> RcaOutput:
    result = _STORE.get(incident_id)
    if not result:
        raise HTTPException(status_code=404, detail="analysis not found")
    return result

"""OpenAI-backed RCA synthesis — symptom vs root cause investigator."""

from __future__ import annotations

import json
import re

import structlog

from rca_agent.config import settings
from rca_agent.schemas.rca_output import (
    AnalyzeRequest,
    ImpactScope,
    RcaOutput,
    SuggestedAction,
    TopologyNeighbor,
)
from rca_agent.topology.graph import get_topology

log = structlog.get_logger()

_SYSTEM = """You are an OpenShift/Kubernetes SRE doing incident investigation.
Separate SYMPTOM (what operators see) from ROOT CAUSE (why it happened).
Return ONLY valid JSON with keys:
incident_id, status, affected_service, affected_namespace,
symptom (string), symptom_confidence (0-1),
probable_root_cause (string), root_cause_confidence (0-1),
confidence (0-1 overall; use average of symptom/root_cause confidences if unsure),
error_subtype (one of: ImagePullBackOff, ErrImagePull, CrashLoopBackOff, OOMKilled,
  NodeNotReady, NodePressure, ProbeFailure, ConfigError, Unknown),
impact_scope (object: namespaces[], workloads[], pods[], nodes[], blast_radius
  one of service|namespace|cluster|unknown; include upstream/downstream neighbor
  names from topology evidence when present),
supporting_evidence (array of strings — quote waiting.message / event messages when present),
business_impact (mention upstream callers / downstream deps when Topo lines exist),
recommended_actions (array of strings),
suggested_actions (array of objects: action, namespace, target, parameters, reason),
automation_available (bool), automation_requires_approval (bool, usually true),
recommended_runbook (string or null).

suggested_actions.action MUST be one of:
  restart-deployment, gitops-scale, scale-deployment, ansible-runbook

Remediation rules by error_subtype:
- ImagePullBackOff / ErrImagePull: DO NOT suggest restart or node-diagnostics.
  Prefer empty suggested_actions; recommend fix image tag / registry / pull secret.
- CrashLoopBackOff: restart-deployment only if evidence suggests transient failure;
  otherwise recommend log/config fix first (may still suggest restart as last resort).
- OOMKilled: prefer gitops-scale (more replicas) OR recommend memory limit increase;
  restart alone is temporary.
- NodeNotReady / NodePressure: ansible-runbook with namespace=aiops-automation,
  target=cluster, parameters.playbook=node-diagnostics.
Prefer gitops-scale over scale-deployment under GitOps/Argo CD.
Be concrete. Prefer evidence over speculation. status must be \"analyzed\".
Do NOT invent namespaces; use the incident namespace when known.
Do NOT invent waiting.message text that is not in evidence."""


def _infer_subtype(evidence: list[str]) -> str:
    blob = "\n".join(evidence)
    for key in (
        "ImagePullBackOff",
        "ErrImagePull",
        "CrashLoopBackOff",
        "OOMKilled",
        "NodeNotReady",
        "DiskPressure",
        "MemoryPressure",
    ):
        if key in blob:
            if key in ("DiskPressure", "MemoryPressure"):
                return "NodePressure"
            return key
    return "Unknown"


def _neighbors(topo: dict | None, key: str) -> list[TopologyNeighbor]:
    out: list[TopologyNeighbor] = []
    for n in (topo or {}).get(key) or []:
        out.append(
            TopologyNeighbor(
                namespace=n.get("namespace"),
                name=n.get("name"),
                id=n.get("id"),
                hops=n.get("hops"),
                kind=n.get("kind"),
            )
        )
    return out


def _impact_from_req(
    req: AnalyzeRequest,
    evidence: list[str],
    topology: dict | None = None,
) -> ImpactScope:
    pods: list[str] = []
    for line in evidence:
        if line.startswith("Pod "):
            name = line.split(":", 1)[0].replace("Pod ", "").strip()
            if name:
                pods.append(name)
    topo = topology or get_topology(req.namespace, req.workload, hops=2)
    upstream = _neighbors(topo, "upstream")
    downstream = _neighbors(topo, "downstream")
    workloads = [req.workload] if req.workload else []
    for n in upstream + downstream:
        if n.name and n.name not in workloads:
            workloads.append(n.name)
    namespaces = [req.namespace] if req.namespace else []
    for n in upstream + downstream:
        if n.namespace and n.namespace not in namespaces:
            namespaces.append(n.namespace)
    if upstream or downstream:
        blast = "namespace" if len(namespaces) == 1 else "cluster"
        if not upstream and len(downstream) <= 2 and len(namespaces) == 1:
            blast = "service"
    else:
        blast = "service" if req.workload else ("namespace" if req.namespace else "unknown")
    return ImpactScope(
        namespaces=namespaces,
        workloads=workloads[:20],
        pods=pods[:10],
        nodes=[],
        blast_radius=blast,
        upstream=upstream,
        downstream=downstream,
        topology_source=(topo or {}).get("source"),
    )


async def synthesize_rca(
    req: AnalyzeRequest,
    evidence: list[str],
    topology: dict | None = None,
) -> RcaOutput:
    from rca_agent.llm_client import chat_completions, llm_configured, model_name

    if not llm_configured():
        return _fallback(
            req, evidence, f"LLM not configured (provider={settings.llm_provider})", topology
        )

    # Keep evidence bounded for local models
    evidence_for_llm = evidence[:25]
    user_content = {
        "incident": req.model_dump(),
        "evidence": evidence_for_llm,
        "topology": topology or get_topology(req.namespace, req.workload, hops=2),
    }
    try:
        content, used_model = await chat_completions(
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": json.dumps(user_content, default=str)},
            ],
            temperature=0.2,
        )
        data = _parse_json(content)
        data.setdefault("incident_id", req.external_id or req.incident_id)
        data.setdefault("affected_namespace", req.namespace)
        data.setdefault("affected_service", req.workload)
        data.setdefault("error_subtype", _infer_subtype(evidence))
        if "root_cause_confidence" not in data and "confidence" in data:
            data["root_cause_confidence"] = data["confidence"]
        if "symptom_confidence" not in data:
            data["symptom_confidence"] = min(0.95, float(data.get("confidence") or 0.5) + 0.1)
        if not data.get("symptom"):
            data["symptom"] = _symptom_from_evidence(evidence)
        enriched = _impact_from_req(req, evidence, topology)
        if not data.get("impact_scope"):
            data["impact_scope"] = enriched.model_dump()
        else:
            # Prefer structured hop neighbors from topology over LLM guesses
            scope = data["impact_scope"] if isinstance(data["impact_scope"], dict) else {}
            scope.setdefault("upstream", [n.model_dump() for n in enriched.upstream])
            scope.setdefault("downstream", [n.model_dump() for n in enriched.downstream])
            scope.setdefault("topology_source", enriched.topology_source)
            if enriched.workloads:
                merged_wl = list(dict.fromkeys([*(scope.get("workloads") or []), *enriched.workloads]))
                scope["workloads"] = merged_wl[:20]
            data["impact_scope"] = scope
        sc = data.get("symptom_confidence")
        rc = data.get("root_cause_confidence")
        if sc is not None and rc is not None:
            data["confidence"] = round((float(sc) + float(rc)) / 2, 3)
        out = RcaOutput.model_validate(data)
        out.model = used_model or model_name()
        out.suggested_actions = _sanitize_suggestions(out)
        return out
    except Exception as exc:  # noqa: BLE001
        log.error("llm_rca_failed", error=str(exc), provider=settings.llm_provider)
        return _fallback(req, evidence, str(exc), topology)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _symptom_from_evidence(evidence: list[str]) -> str:
    for line in evidence:
        for key in ("ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff", "OOMKilled"):
            if key in line:
                return f"Containers reporting {key}"
    return "Degraded or failing workload observed"


def _sanitize_suggestions(out: RcaOutput) -> list[SuggestedAction]:
    subtype = (out.error_subtype or "").lower()
    cleaned: list[SuggestedAction] = []
    for s in out.suggested_actions:
        action = (s.action or "").strip()
        params = dict(s.parameters or {})
        # normalize wrong ansible shape: target=node-diagnostics → parameters.playbook
        if action == "ansible-runbook":
            if s.target and s.target not in ("cluster", "node") and "playbook" not in params:
                params["playbook"] = s.target
                s = s.model_copy(
                    update={"target": "cluster", "namespace": s.namespace or "aiops-automation", "parameters": params}
                )
            else:
                s = s.model_copy(
                    update={
                        "namespace": s.namespace or "aiops-automation",
                        "target": s.target or "cluster",
                        "parameters": params or {"playbook": "node-diagnostics"},
                    }
                )
        if subtype in {"imagepullbackoff", "errimagepull", "invalidimagename"}:
            if action in {"restart-deployment", "ansible-runbook", "scale-deployment", "gitops-scale"}:
                continue
        cleaned.append(s)
    return cleaned[:3]


def _business_impact_from_topo(topology: dict | None) -> str:
    if not topology:
        return "Unknown — manual review required"
    up = topology.get("upstream") or []
    down = topology.get("downstream") or []
    if not up and not down:
        return "Unknown — manual review required"
    parts = []
    if up:
        names = ", ".join(f"{n.get('name')}" for n in up[:4] if n.get("name"))
        parts.append(f"upstream callers may be affected: {names}")
    if down:
        names = ", ".join(f"{n.get('name')}" for n in down[:4] if n.get("name"))
        parts.append(f"downstream deps: {names}")
    return "; ".join(parts)


def _fallback(
    req: AnalyzeRequest,
    evidence: list[str],
    reason: str,
    topology: dict | None = None,
) -> RcaOutput:
    subtype = _infer_subtype(evidence)
    symptom = _symptom_from_evidence(evidence)
    cause = "Insufficient automated analysis"
    waiting_msg = None
    for line in evidence:
        if "waiting.message=" in line:
            waiting_msg = line.split("waiting.message=", 1)[1][:200]
        if any(x in line for x in ("OOMKilled", "CrashLoopBackOff", "ImagePullBackOff", "Evicted")):
            cause = line[:240]
            break
    if waiting_msg and subtype in {"ImagePullBackOff", "ErrImagePull"}:
        cause = f"Image pull failure: {waiting_msg}"
    elif subtype == "ImagePullBackOff":
        cause = "Container cannot pull image (registry/auth/tag). Symptom is ImagePullBackOff; root cause is pull configuration or image availability."

    suggested: list[SuggestedAction] = []
    if req.namespace and req.workload:
        if subtype == "CrashLoopBackOff":
            suggested.append(
                SuggestedAction(
                    action="restart-deployment",
                    namespace=req.namespace,
                    target=req.workload,
                    parameters={},
                    reason="Fallback NBA: CrashLoopBackOff — restart after approval",
                )
            )
        elif subtype == "OOMKilled":
            suggested.append(
                SuggestedAction(
                    action="gitops-scale",
                    namespace=req.namespace,
                    target=req.workload,
                    parameters={"replicas": 2},
                    reason="Fallback NBA: OOMKilled — scale via GitOps (temporary capacity)",
                )
            )
        elif subtype in {"NodeNotReady", "NodePressure"}:
            suggested.append(
                SuggestedAction(
                    action="ansible-runbook",
                    namespace="aiops-automation",
                    target="cluster",
                    parameters={"playbook": "node-diagnostics"},
                    reason="Fallback NBA: node pressure / not ready",
                )
            )
        # ImagePull: no auto remediation draft

    symptom_c = 0.85 if subtype != "Unknown" else 0.4
    root_c = 0.55 if waiting_msg else (0.35 if evidence else 0.15)

    return RcaOutput(
        incident_id=req.external_id or req.incident_id,
        status="analyzed",
        affected_service=req.workload,
        affected_namespace=req.namespace,
        symptom=symptom,
        symptom_confidence=symptom_c,
        probable_root_cause=f"{cause} (fallback: {reason})",
        root_cause_confidence=root_c,
        confidence=round((symptom_c + root_c) / 2, 3),
        error_subtype=subtype,
        impact_scope=_impact_from_req(req, evidence, topology),
        supporting_evidence=evidence[:20] or [reason],
        business_impact=_business_impact_from_topo(topology),
        recommended_actions=_fallback_recommendations(subtype),
        suggested_actions=suggested,
        automation_available=bool(suggested),
        automation_requires_approval=True,
        recommended_runbook=None,
        model="fallback",
    )


def _fallback_recommendations(subtype: str) -> list[str]:
    if subtype in {"ImagePullBackOff", "ErrImagePull"}:
        return [
            "Verify image name/tag and Harbor project access",
            "Check imagePullSecrets and registry connectivity from the node",
            "Do not restart until the image can be pulled",
        ]
    if subtype == "CrashLoopBackOff":
        return [
            "Inspect container logs and previous terminated message",
            "Validate config/env and probes",
            "Consider restart-deployment after fixing config (requires approval)",
        ]
    if subtype == "OOMKilled":
        return [
            "Increase memory requests/limits via GitOps",
            "Check for memory leaks / traffic spike",
        ]
    return [
        "Inspect pod events and logs in the affected namespace",
        "Compare recent deployments / config changes",
        "Validate resource limits and probes",
    ]

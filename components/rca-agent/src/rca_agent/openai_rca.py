"""OpenAI-backed RCA synthesis — symptom vs root cause investigator."""

from __future__ import annotations

import json
import re

import httpx
import structlog

from rca_agent.config import settings
from rca_agent.schemas.rca_output import AnalyzeRequest, ImpactScope, RcaOutput, SuggestedAction

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
  one of service|namespace|cluster|unknown),
supporting_evidence (array of strings — quote waiting.message / event messages when present),
business_impact, recommended_actions (array of strings),
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


def _impact_from_req(req: AnalyzeRequest, evidence: list[str]) -> ImpactScope:
    pods: list[str] = []
    for line in evidence:
        if line.startswith("Pod "):
            name = line.split(":", 1)[0].replace("Pod ", "").strip()
            if name:
                pods.append(name)
    return ImpactScope(
        namespaces=[req.namespace] if req.namespace else [],
        workloads=[req.workload] if req.workload else [],
        pods=pods[:10],
        nodes=[],
        blast_radius="service" if req.workload else ("namespace" if req.namespace else "unknown"),
    )


async def synthesize_rca(req: AnalyzeRequest, evidence: list[str]) -> RcaOutput:
    if not settings.openai_api_key:
        return _fallback(req, evidence, "OPENAI_API_KEY missing")

    user_content = {
        "incident": req.model_dump(),
        "evidence": evidence,
    }
    payload = {
        "model": settings.openai_model,
        "temperature": 0.2,
        "max_tokens": settings.openai_max_tokens,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(user_content, default=str)},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=float(settings.rca_request_timeout_seconds)) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code >= 400:
                log.error("openai_http_error", status=resp.status_code, body=resp.text[:500])
                return _fallback(req, evidence, f"OpenAI HTTP {resp.status_code}")
            content = resp.json()["choices"][0]["message"]["content"]
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
            if not data.get("impact_scope"):
                data["impact_scope"] = _impact_from_req(req, evidence).model_dump()
            # overall confidence
            sc = data.get("symptom_confidence")
            rc = data.get("root_cause_confidence")
            if sc is not None and rc is not None:
                data["confidence"] = round((float(sc) + float(rc)) / 2, 3)
            out = RcaOutput.model_validate(data)
            out.model = settings.openai_model
            out.suggested_actions = _sanitize_suggestions(out)
            return out
    except Exception as exc:  # noqa: BLE001
        log.error("openai_rca_failed", error=str(exc))
        return _fallback(req, evidence, str(exc))


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


def _fallback(req: AnalyzeRequest, evidence: list[str], reason: str) -> RcaOutput:
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
        impact_scope=_impact_from_req(req, evidence),
        supporting_evidence=evidence[:20] or [reason],
        business_impact="Unknown — manual review required",
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

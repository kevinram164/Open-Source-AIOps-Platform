"""OpenAI-backed RCA synthesis."""

from __future__ import annotations

import json
import re

import httpx
import structlog

from rca_agent.config import settings
from rca_agent.schemas.rca_output import AnalyzeRequest, RcaOutput, SuggestedAction

log = structlog.get_logger()

_SYSTEM = """You are an OpenShift/Kubernetes SRE doing root cause analysis.
Return ONLY valid JSON with keys:
incident_id, status, affected_service, affected_namespace, probable_root_cause,
confidence (0-1), supporting_evidence (array of strings), business_impact,
recommended_actions (array of strings),
suggested_actions (array of objects with action, namespace, target, parameters, reason),
automation_available (bool), automation_requires_approval (bool, usually true),
recommended_runbook (string or null).
suggested_actions.action MUST be one of:
  restart-deployment, gitops-scale, scale-deployment, ansible-runbook
Prefer gitops-scale over scale-deployment when changing replicas under GitOps/Argo CD.
For node issues use ansible-runbook with parameters.playbook=node-diagnostics.
Be concrete. Prefer evidence over speculation. status must be \"analyzed\".
Do NOT invent namespaces; use the incident namespace when known."""


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
            out = RcaOutput.model_validate(data)
            out.model = settings.openai_model
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


def _fallback(req: AnalyzeRequest, evidence: list[str], reason: str) -> RcaOutput:
    cause = "Insufficient automated analysis"
    for line in evidence:
        if any(x in line for x in ("OOMKilled", "CrashLoopBackOff", "ImagePullBackOff", "Evicted")):
            cause = line
            break
    suggested: list = []
    blob = "\n".join(evidence)
    if req.namespace and req.workload and any(
        x in blob for x in ("CrashLoopBackOff", "ImagePullBackOff", "OOMKilled")
    ):
        suggested.append(
            SuggestedAction(
                action="restart-deployment",
                namespace=req.namespace,
                target=req.workload,
                parameters={},
                reason="Fallback NBA: pod failure signature in evidence",
            )
        )
    return RcaOutput(
        incident_id=req.external_id or req.incident_id,
        status="analyzed",
        affected_service=req.workload,
        affected_namespace=req.namespace,
        probable_root_cause=f"{cause} (fallback: {reason})",
        confidence=0.35 if evidence else 0.15,
        supporting_evidence=evidence[:20] or [reason],
        business_impact="Unknown — manual review required",
        recommended_actions=[
            "Inspect pod events and logs in the affected namespace",
            "Compare recent deployments / config changes",
            "Validate resource limits and probes",
        ],
        suggested_actions=suggested,
        automation_available=bool(suggested),
        automation_requires_approval=True,
        recommended_runbook=None,
        model="fallback",
    )

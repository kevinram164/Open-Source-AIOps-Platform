"""AIOps Chat — natural-language Q&A over incidents/RCA/NBA (demo API)."""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_api.analyze import run_analyze
from incident_api.config import settings
from incident_api.models import Incident, RcaResult

log = structlog.get_logger()

# Demo aliases for banking / movie lab
_SERVICE_HINTS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"payment|transfer", re.I), "npd-banking", "transfer-service"),
    (re.compile(r"auth", re.I), "npd-banking", "auth-service"),
    (re.compile(r"account", re.I), "npd-banking", "account-service"),
    (re.compile(r"frontend|banking\s*ui", re.I), "npd-banking", "frontend"),
    (re.compile(r"notification", re.I), "npd-banking", "notification-service"),
    (re.compile(r"movie[\s-]?web|cinehome|phim", re.I), "npd-movie", "movie-web"),
    (re.compile(r"movie[\s-]?api", re.I), "npd-movie", "movie-api"),
    (re.compile(r"media[\s-]?worker", re.I), "npd-movie", "media-worker"),
]


def _hints_from_question(question: str) -> tuple[str | None, str | None]:
    for pat, ns, workload in _SERVICE_HINTS:
        if pat.search(question):
            return ns, workload
    return None, None


async def resolve_incident(
    session: AsyncSession,
    *,
    question: str,
    namespace: str | None,
    incident_ref: str | None,
) -> Incident | None:
    if incident_ref:
        try:
            uid = UUID(incident_ref)
            inc = await session.get(Incident, uid)
            if inc:
                return inc
        except ValueError:
            pass
        result = await session.execute(
            select(Incident).where(Incident.external_id == incident_ref.upper())
        )
        inc = result.scalar_one_or_none()
        if inc:
            return inc

    hint_ns, hint_wl = _hints_from_question(question)
    ns = namespace or hint_ns
    tokens = [t for t in re.split(r"[^a-zA-Z0-9_-]+", question.lower()) if len(t) > 2]

    stmt = select(Incident).order_by(Incident.created_at.desc()).limit(50)
    if ns:
        stmt = select(Incident).where(Incident.namespace == ns).order_by(Incident.created_at.desc()).limit(50)
    rows = list((await session.execute(stmt)).scalars().all())

    if hint_wl:
        for inc in rows:
            if (inc.workload or "").lower() == hint_wl.lower():
                return inc
            if hint_wl.lower() in (inc.title or "").lower():
                return inc

    for inc in rows:
        blob = f"{inc.title} {inc.workload} {inc.namespace}".lower()
        if any(t in blob for t in tokens if t not in {"why", "is", "the", "down", "what", "how"}):
            return inc

    return rows[0] if rows else None


async def latest_rca(session: AsyncSession, incident_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(
        select(RcaResult)
        .where(RcaResult.incident_id == incident_id)
        .order_by(RcaResult.created_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return dict(row.result) if row and row.result else None


async def list_remediations_for_incident(external_id: str) -> list[dict[str, Any]]:
    base = settings.remediation_controller_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{base}/api/v1/remediations")
            if resp.status_code >= 400:
                return []
            items = resp.json()
            return [i for i in items if i.get("incident_id") == external_id][:10]
    except Exception as exc:  # noqa: BLE001
        log.warning("chat_list_remediations_failed", error=str(exc))
        return []


def _template_answer(
    *,
    question: str,
    incident: Incident,
    rca: dict[str, Any],
) -> tuple[str, list[str], str]:
    cause = rca.get("probable_root_cause") or "Root cause not yet determined"
    evidence = list(rca.get("supporting_evidence") or [])[:8]
    actions = list(rca.get("recommended_actions") or [])
    recommendation = actions[0] if actions else (rca.get("recommended_runbook") or "Review RCA and approve NBA remediation if appropriate")
    svc = rca.get("affected_service") or incident.workload or "the service"
    answer = (
        f"{svc} appears impacted: {cause}\n\n"
        f"Evidence\n"
        + "\n".join(f"- {e}" for e in evidence)
        + (f"\n\nRecommendation\n{recommendation}" if recommendation else "")
    )
    if not evidence:
        answer = (
            f"Based on incident {incident.external_id} ({incident.title}): {cause}\n\n"
            f"Recommendation\n{recommendation}"
        )
    return answer, evidence, recommendation


async def synthesize_with_openai(
    *,
    question: str,
    incident: Incident,
    rca: dict[str, Any],
    remediations: list[dict[str, Any]],
) -> tuple[str, list[str], str, str] | None:
    if not settings.openai_api_key:
        return None

    context = {
        "question": question,
        "incident": {
            "external_id": incident.external_id,
            "title": incident.title,
            "namespace": incident.namespace,
            "workload": incident.workload,
            "status": incident.status.value,
            "severity": incident.severity.value if incident.severity else None,
        },
        "rca": {
            "probable_root_cause": rca.get("probable_root_cause"),
            "confidence": rca.get("confidence"),
            "supporting_evidence": rca.get("supporting_evidence"),
            "recommended_actions": rca.get("recommended_actions"),
            "suggested_actions": rca.get("suggested_actions"),
            "affected_service": rca.get("affected_service"),
            "affected_namespace": rca.get("affected_namespace"),
        },
        "pending_remediations": remediations,
    }
    system = (
        "You are an OpenShift AIOps assistant for a customer demo. "
        "Answer ONLY from the provided JSON context. "
        "Return ONLY valid JSON with keys: answer (string, clear prose like an SRE briefing), "
        "evidence (array of short bullet strings), recommendation (string). "
        "Do not invent metrics. Mention that remediations stay pending until human approve. "
        "Keep answer under 250 words."
    )
    payload = {
        "model": settings.openai_model,
        "temperature": 0.2,
        "max_tokens": 800,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, default=str)},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code >= 400:
                log.error("chat_openai_http", status=resp.status_code, body=resp.text[:300])
                return None
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            data = json.loads(content)
            return (
                str(data.get("answer") or ""),
                list(data.get("evidence") or []),
                str(data.get("recommendation") or ""),
                settings.openai_model,
            )
    except Exception as exc:  # noqa: BLE001
        log.error("chat_openai_failed", error=str(exc))
        return None


async def handle_chat(
    session: AsyncSession,
    *,
    question: str,
    namespace: str | None,
    incident_ref: str | None,
    auto_analyze: bool,
) -> dict[str, Any]:
    incident = await resolve_incident(
        session, question=question, namespace=namespace, incident_ref=incident_ref
    )
    if not incident:
        return {
            "answer": (
                "I could not find a matching open incident. "
                "Ingest an alert or create an incident first, then ask again "
                "(optionally pass incident_id / namespace)."
            ),
            "evidence": [],
            "recommendation": None,
            "probable_root_cause": None,
            "confidence": None,
            "incident": None,
            "nba": None,
            "remediations": [],
            "model": "none",
        }

    rca = await latest_rca(session, incident.id)
    nba_block: dict[str, Any] | None = None
    if auto_analyze and not rca:
        analyzed = await run_analyze(session, incident)
        rca = analyzed.get("rca") if isinstance(analyzed.get("rca"), dict) else {}
        nba_block = analyzed.get("nba")
        await session.refresh(incident)
    else:
        stored_nba = (rca or {}).get("nba")
        if isinstance(stored_nba, dict):
            nba_block = stored_nba
        elif isinstance(stored_nba, list):
            nba_block = {"remediations": stored_nba}

    rca = rca or {}
    remediations = await list_remediations_for_incident(incident.external_id)

    synthesized = await synthesize_with_openai(
        question=question, incident=incident, rca=rca, remediations=remediations
    )
    if synthesized:
        answer, evidence, recommendation, model = synthesized
    else:
        answer, evidence, recommendation = _template_answer(
            question=question, incident=incident, rca=rca
        )
        model = "template"

    return {
        "answer": answer,
        "evidence": evidence,
        "recommendation": recommendation,
        "probable_root_cause": rca.get("probable_root_cause"),
        "confidence": rca.get("confidence"),
        "incident": {
            "id": str(incident.id),
            "external_id": incident.external_id,
            "title": incident.title,
            "namespace": incident.namespace,
            "workload": incident.workload,
            "status": incident.status.value,
        },
        "nba": nba_block,
        "remediations": remediations,
        "model": model,
    }

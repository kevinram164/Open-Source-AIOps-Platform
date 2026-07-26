"""AIOps Chat — investigator: resolve workload, ops Q&A, restart commands."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_api.analyze import run_analyze
from incident_api.chat_memory import load_session_history, save_turn, suggest_followups
from incident_api.config import settings
from incident_api.models import Incident, RcaResult
from incident_api.nba import create_pending_remediations
from incident_api.schemas_chat import new_session_id

log = structlog.get_logger()


def _as_str_list(value: Any, *, limit: int = 40) -> list[str]:
    """Normalize evidence to list[str]. Never list(string) → char-by-char."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        # bullet / newline separated blob from LLM
        if "\n" in text:
            return [ln.strip(" -•\t") for ln in text.splitlines() if ln.strip()][:limit]
        return [text][:limit]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                # skip accidental single-char noise from bad list(string)
                if len(item) == 1 and item.isalnum():
                    continue
                out.append(item.strip())
            elif item is not None:
                out.append(str(item))
        # If we filtered everything because LLM returned char array, rejoin
        if not out and value and all(isinstance(x, str) and len(x) == 1 for x in value):
            joined = "".join(value).strip()
            return [joined] if joined else []
        return out[:limit]
    return [str(value)][:limit]


# Demo aliases for banking / movie lab
_SERVICE_HINTS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"payment|transfer[\s_-]?service|transfer", re.I), "npd-banking", "transfer-service"),
    (re.compile(r"auth[\s_-]?service|\bauth\b", re.I), "npd-banking", "auth-service"),
    (re.compile(r"account[\s_-]?service|account", re.I), "npd-banking", "account-service"),
    (re.compile(r"frontend|banking\s*ui", re.I), "npd-banking", "frontend"),
    (re.compile(r"notification", re.I), "npd-banking", "notification-service"),
    (re.compile(r"movie[\s-]?web|cinehome|phim", re.I), "npd-movie", "movie-web"),
    (re.compile(r"movie[\s-]?api", re.I), "npd-movie", "movie-api"),
    (re.compile(r"media[\s-]?worker", re.I), "npd-movie", "media-worker"),
]

_RESTART_CMD = re.compile(
    r"(?:restart|rollout\s+restart|khởi\s*động\s*lại)\s+"
    r"(?:pod|deployment|deploy)?\s*([a-z0-9][a-z0-9._-]*)",
    re.I,
)
_NS_IN_Q = re.compile(r"(?:in|namespace|ns)\s+([a-z0-9][a-z0-9-]*)", re.I)
# Only when operator clearly wants RCA / incident deep-dive
_INVESTIGATE = re.compile(
    r"\bwhy\b|tại\s*sao|gì\s*vậy|root\s*cause|rca|"
    r"(?:is|are)\s+.+\s+down|bị\s*down|sự\s*cố|incident\s+(?:INC-|#)|"
    r"phân\s*tích\s*(?:lỗi|incident|sự\s*cố)",
    re.I,
)


def detect_intent(question: str) -> str:
    """Platform ops Q&A is the default — not incident-centric."""
    if _RESTART_CMD.search(question):
        return "command_restart"
    if _INVESTIGATE.search(question):
        return "investigate"
    return "ops_query"


def _hints_from_question(question: str) -> tuple[str | None, str | None]:
    for pat, ns, workload in _SERVICE_HINTS:
        if pat.search(question):
            return ns, workload
    # explicit workload-looking tokens
    m = re.search(r"\b([a-z][a-z0-9-]+-service)\b", question, re.I)
    if m:
        name = m.group(1).lower()
        for _, ns, wl in _SERVICE_HINTS:
            if wl == name:
                return ns, wl
        return None, name
    return None, None


def _score_incident(
    inc: Incident,
    *,
    hint_ns: str | None,
    hint_wl: str | None,
    tokens: list[str],
) -> int:
    score = 0
    wl = (inc.workload or "").lower()
    ns = (inc.namespace or "").lower()
    title = (inc.title or "").lower()
    status = getattr(inc.status, "value", str(inc.status)).lower()

    if hint_wl and wl == hint_wl.lower():
        score += 100
    elif hint_wl and hint_wl.lower() in wl:
        score += 70
    elif hint_wl and hint_wl.lower() in title:
        score += 50

    if hint_ns and ns == hint_ns.lower():
        score += 25
    elif hint_ns and ns == hint_ns.lower() and not wl:
        # namespace-only incident — weak match when we wanted a workload
        score -= 40 if hint_wl else 0

    stop = {"why", "is", "the", "down", "what", "how", "pod", "service", "namespace"}
    for t in tokens:
        if t in stop:
            continue
        if t in wl:
            score += 15
        if t in title:
            score += 8
        if t in ns:
            score += 3

    if status in {"open", "analyzing", "investigating"}:
        score += 10
    if wl:  # prefer incidents that name a workload
        score += 5
    return score


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

    stmt = select(Incident).order_by(Incident.created_at.desc()).limit(80)
    if ns:
        stmt = (
            select(Incident)
            .where(Incident.namespace == ns)
            .order_by(Incident.created_at.desc())
            .limit(80)
        )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return None

    ranked = sorted(
        rows,
        key=lambda i: _score_incident(i, hint_ns=hint_ns or ns, hint_wl=hint_wl, tokens=tokens),
        reverse=True,
    )
    best = ranked[0]
    best_score = _score_incident(best, hint_ns=hint_ns or ns, hint_wl=hint_wl, tokens=tokens)
    # If user asked for a specific workload but best is namespace-only weak match, still return best
    # but prefer any row with exact workload even outside ns filter
    if hint_wl and (best.workload or "").lower() != hint_wl.lower():
        all_rows = list(
            (
                await session.execute(
                    select(Incident).order_by(Incident.created_at.desc()).limit(120)
                )
            ).scalars().all()
        )
        for inc in all_rows:
            if (inc.workload or "").lower() == hint_wl.lower():
                return inc
            if hint_wl.lower() in (inc.title or "").lower() and inc.workload:
                return inc
        if best_score < 20:
            return None
    return best


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


async def fetch_ops_context(
    question: str, namespace: str | None = None
) -> dict[str, Any]:
    """Multi-facet platform context — answers many question types without topic routing."""
    url = f"{settings.rca_agent_url.rstrip('/')}/api/v1/ops/context"
    # Keep headroom under ~120s browser/proxy cutoffs when LLM also runs
    ops_timeout = 25.0 if (settings.llm_provider or "").lower() == "ollama" else 60.0
    try:
        async with httpx.AsyncClient(timeout=ops_timeout) as client:
            resp = await client.post(
                url, json={"question": question, "namespace": namespace}
            )
            if resp.status_code >= 400:
                return {
                    "warnings": [f"ops context HTTP {resp.status_code}"],
                    "facts": {},
                    "evidence": [],
                    "summary": {},
                }
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("ops_context_failed", error=str(exc))
        return {"warnings": [str(exc)], "facts": {}, "evidence": [], "summary": {}}


async def recent_incidents_brief(
    session: AsyncSession, *, namespace: str | None = None, limit: int = 8
) -> list[dict[str, Any]]:
    stmt = select(Incident).order_by(Incident.created_at.desc()).limit(limit)
    if namespace:
        stmt = (
            select(Incident)
            .where(Incident.namespace == namespace)
            .order_by(Incident.created_at.desc())
            .limit(limit)
        )
    rows = list((await session.execute(stmt)).scalars().all())
    return [
        {
            "external_id": i.external_id,
            "title": i.title,
            "namespace": i.namespace,
            "workload": i.workload,
            "status": i.status.value,
            "severity": i.severity.value if i.severity else None,
        }
        for i in rows
    ]


async def resolve_deployment(namespace: str, pod_name: str) -> str | None:
    url = f"{settings.rca_agent_url.rstrip('/')}/api/v1/ops/resolve-deployment"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url, json={"namespace": namespace, "pod_name": pod_name}
            )
            if resp.status_code >= 400:
                return None
            return resp.json().get("deployment")
    except Exception as exc:  # noqa: BLE001
        log.warning("resolve_deployment_failed", error=str(exc))
        return None


def _template_answer(*, incident: Incident, rca: dict[str, Any]) -> tuple[str, list[str], str]:
    symptom = rca.get("symptom")
    cause = rca.get("probable_root_cause") or "Root cause not yet determined"
    evidence = list(rca.get("supporting_evidence") or [])[:10]
    actions = list(rca.get("recommended_actions") or [])
    recommendation = actions[0] if actions else (
        rca.get("recommended_runbook") or "Review RCA and approve NBA remediation if appropriate"
    )
    svc = rca.get("affected_service") or incident.workload or "the service"
    subtype = rca.get("error_subtype") or "Unknown"
    sc = rca.get("symptom_confidence")
    rc = rca.get("root_cause_confidence")
    parts = [f"{svc} — subtype={subtype}"]
    if symptom:
        parts.append(f"Symptom (confidence {sc}): {symptom}")
    parts.append(f"Root cause (confidence {rc}): {cause}")
    if evidence:
        parts.append("Evidence\n" + "\n".join(f"- {e}" for e in evidence))
    parts.append(f"Recommendation\n{recommendation}")
    return "\n\n".join(parts), evidence, recommendation


def _ops_fallback_brief(question: str, payload: dict[str, Any]) -> tuple[str, list[str], str]:
    """Fallback when LLM unavailable — show compact multi-facet brief, not one topic."""
    summary = payload.get("summary") or {}
    facts = payload.get("facts") or {}
    disk = facts.get("disk") if isinstance(facts.get("disk"), dict) else {}
    evidence = _as_str_list(payload.get("evidence"), limit=20)
    highlights = summary.get("highlights") or []
    counts = summary.get("counts") or {}
    q = (question or "").lower()
    parts = [
        f"Câu hỏi: {question}",
        f"Scope: {summary.get('scope', 'cluster')} · metrics={summary.get('metrics_source', 'n/a')}",
    ]
    # Prefer question-relevant facts first (PVC / disk)
    if any(k in q for k in ("pvc", "disk", "filesystem", "ổ cứng", "dung lượng")):
        pvc_hi = [
            p
            for p in (disk.get("pvc_usage") or [])
            if isinstance(p, dict) and float(p.get("usage_percent") or p.get("pct") or 0) >= 80
        ][:8]
        if not pvc_hi:
            pvc_hi = (disk.get("pvc_usage") or [])[:8]
        pressure = disk.get("nodes_disk_pressure") or []
        node_fs = disk.get("node_filesystem") or []
        if pvc_hi:
            parts.append(
                "PVC usage:\n"
                + "\n".join(
                    f"- {p.get('namespace', '?')}/{p.get('name') or p.get('pvc')}: "
                    f"{p.get('usage_percent') or p.get('pct') or '?'}%"
                    for p in pvc_hi
                    if isinstance(p, dict)
                )
            )
        if pressure:
            parts.append(
                "Nodes DiskPressure=True:\n"
                + "\n".join(f"- {n.get('name') or n}" for n in pressure[:8])
            )
        if node_fs:
            parts.append(
                "Node filesystem:\n"
                + "\n".join(
                    f"- {n.get('node') or n.get('instance')}: {n.get('usage_percent') or n.get('pct')}%"
                    for n in node_fs[:8]
                    if isinstance(n, dict)
                )
            )
        issues = facts.get("pvc_issues") or []
        if issues:
            parts.append(
                "PVC issues:\n"
                + "\n".join(f"- {i}" if isinstance(i, str) else f"- {i}" for i in issues[:6])
            )
    if highlights:
        parts.append("Highlights:\n" + "\n".join(f"- {h}" for h in highlights[:8]))
    if counts:
        parts.append(
            "Counts: "
            + ", ".join(f"{k}={v}" for k, v in counts.items() if v)
        )
    top = facts.get("top_cpu_pods") or []
    if top and "cpu" in q:
        parts.append(
            "Top CPU:\n"
            + "\n".join(
                f"- {p.get('namespace')}/{p.get('name')}: {p.get('cpu')}" for p in top[:5]
            )
        )
    parts.append(
        "LLM chưa kịp (timeout <120s để tránh ERR_EMPTY_RESPONSE). "
        "Facts trên lấy từ context pack."
    )
    return (
        "\n\n".join(parts),
        evidence,
        "Hỏi lại; khi Ollama trả lời kịp sẽ có badge model qwen2.5:3b.",
    )


async def _synthesize_bounded(**kwargs: Any) -> tuple[str, list[str], str, str] | None:
    """Hard-cap LLM wait so Chat returns before ~120s proxy/browser cutoffs."""
    # leave ~30s for ops context + serialization under a 120s wall
    cap = float(settings.ollama_timeout_seconds)
    if (settings.llm_provider or "").lower() == "ollama":
        cap = min(cap, 75.0)
    else:
        cap = min(cap, 55.0)
    try:
        return await asyncio.wait_for(synthesize_with_openai(**kwargs), timeout=cap)
    except asyncio.TimeoutError:
        log.error("chat_llm_deadline", timeout_s=cap, provider=settings.llm_provider)
        return None


async def synthesize_with_openai(
    *,
    question: str,
    incident: Incident | None,
    rca: dict[str, Any],
    remediations: list[dict[str, Any]],
    ops_payload: dict[str, Any] | None = None,
    recent_incidents: list[dict[str, Any]] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> tuple[str, list[str], str, str] | None:
    from incident_api.llm_client import chat_completions, llm_configured

    if not llm_configured():
        return None

    use_ollama = (settings.llm_provider or "").lower() == "ollama"

    # Shrink context for local CPU models (large prompts → truncate@2048 → hang → 500@3m)
    if ops_payload and use_ollama:
        facts = ops_payload.get("facts") or {}
        disk = facts.get("disk") or {}
        if isinstance(disk, dict):
            disk = {
                "nodes_disk_pressure": (disk.get("nodes_disk_pressure") or [])[:5],
                "node_filesystem": (disk.get("node_filesystem") or [])[:8],
                "pvc_usage": (disk.get("pvc_usage") or [])[:8],
            }
        ops_payload = {
            "summary": {
                "scope": (ops_payload.get("summary") or {}).get("scope"),
                "metrics_source": (ops_payload.get("summary") or {}).get("metrics_source"),
                "highlights": ((ops_payload.get("summary") or {}).get("highlights") or [])[:6],
                "counts": (ops_payload.get("summary") or {}).get("counts"),
            },
            "evidence": (ops_payload.get("evidence") or [])[:10],
            "facts": {
                "top_cpu_pods": (facts.get("top_cpu_pods") or [])[:5],
                "top_memory_pods": (facts.get("top_memory_pods") or [])[:3],
                "node_usage": (facts.get("node_usage") or [])[:5],
                "crashloop_pods": (facts.get("crashloop_pods") or [])[:5],
                "imagepull_pods": (facts.get("imagepull_pods") or [])[:3],
                "pvc_issues": (facts.get("pvc_issues") or [])[:4],
                "disk": disk,
                "hpas": [h for h in (facts.get("hpas") or []) if h.get("at_max")][:3],
            },
        }

    context: dict[str, Any] = {
        "question": question,
        "pending_remediations": (remediations or [])[:3],
        "recent_incidents": (recent_incidents or [])[:3],
        "conversation_history": (conversation_history or [])[-4:],
    }
    if ops_payload:
        context["platform_context"] = {
            "summary": ops_payload.get("summary"),
            "facts": ops_payload.get("facts"),
            "evidence": ops_payload.get("evidence"),
            "warnings": (ops_payload.get("warnings") or [])[:5],
        }
    if rca:
        context["rca"] = {
            "symptom": rca.get("symptom"),
            "probable_root_cause": rca.get("probable_root_cause"),
            "error_subtype": rca.get("error_subtype"),
            "supporting_evidence": (rca.get("supporting_evidence") or [])[:6],
            "recommended_actions": (rca.get("recommended_actions") or [])[:3],
            "affected_service": rca.get("affected_service"),
            "affected_namespace": rca.get("affected_namespace"),
        }
    if incident:
        context["incident"] = {
            "external_id": incident.external_id,
            "title": incident.title,
            "namespace": incident.namespace,
            "workload": incident.workload,
            "status": incident.status.value,
        }
    if use_ollama:
        system = (
            "OpenShift ops assistant. Answer ONLY the question from facts. "
            "No inventing. Return ONLY JSON: "
            '{"answer":"...","evidence":["..."],"recommendation":"..."}. '
            "Max 120 words. Same language as the question."
        )
        max_tok = 350
    else:
        system = (
            "You are a general OpenShift platform operations assistant. "
            "The operator may ask ANY day-2 question (CPU, memory, nodes, deployments, "
            "CrashLoop, ImagePull, PVC, HPA, incidents, capacity, what is noteworthy, etc.). "
            "Use platform_context + recent_incidents + rca + conversation_history. "
            "If the user refers to prior turns (e.g. 'còn pod nào nữa?'), use conversation_history. "
            "Answer ONLY the asked question — pick the relevant facts; "
            "do not dump unrelated sections. "
            "If the needed fact is missing, say what is missing — do not invent. "
            "Return ONLY valid JSON: answer, evidence (array of short strings), "
            "recommendation. Remediations require human approve. "
            "Keep under 280 words. Match the question language."
        )
        max_tok = 900
    user_content = json.dumps(context, default=str, separators=(",", ":"))
    if use_ollama and len(user_content) > 6000:
        user_content = user_content[:6000] + "…(truncated)"
    try:
        content, used_model = await chat_completions(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=max_tok,
        )
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        data = json.loads(content)
        return (
            str(data.get("answer") or ""),
            _as_str_list(data.get("evidence")),
            str(data.get("recommendation") or ""),
            used_model,
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "chat_llm_failed",
            error=repr(exc) or type(exc).__name__,
            provider=settings.llm_provider,
        )
        return None


def _empty_response(answer: str, intent: str, **extra: Any) -> dict[str, Any]:
    base = {
        "session_id": None,
        "intent": intent,
        "answer": answer,
        "evidence": [],
        "recommendation": None,
        "suggested_followups": [],
        "symptom": None,
        "symptom_confidence": None,
        "probable_root_cause": None,
        "root_cause_confidence": None,
        "confidence": None,
        "error_subtype": None,
        "impact_scope": None,
        "incident": None,
        "nba": None,
        "remediations": [],
        "ops_snapshot": None,
        "model": "none",
    }
    base.update(extra)
    return base


async def _finalize_chat(
    session: AsyncSession,
    *,
    session_id: str,
    question: str,
    namespace: str | None,
    result: dict[str, Any],
    ops: dict[str, Any] | None = None,
) -> dict[str, Any]:
    intent = result.get("intent") or "ops_query"
    followups = result.get("suggested_followups") or suggest_followups(
        intent=intent,
        question=question,
        namespace=namespace,
        ops=ops,
        incident=result.get("incident") if isinstance(result.get("incident"), dict) else None,
    )
    result["session_id"] = session_id
    result["suggested_followups"] = followups
    result["evidence"] = _as_str_list(result.get("evidence"))

    try:
        await save_turn(
            session,
            session_id=session_id,
            role="user",
            content=question,
            namespace=namespace,
            intent=intent,
        )
        await save_turn(
            session,
            session_id=session_id,
            role="assistant",
            content=str(result.get("answer") or ""),
            namespace=namespace,
            intent=intent,
            model=result.get("model"),
            meta={
                "evidence": (result.get("evidence") or [])[:15],
                "recommendation": result.get("recommendation"),
                "followups": followups,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("chat_audit_save_failed", error=str(exc))

    return result


async def _handle_restart_command(
    session: AsyncSession,
    *,
    question: str,
    namespace: str | None,
) -> dict[str, Any]:
    m = _RESTART_CMD.search(question)
    if not m:
        return _empty_response("Không parse được tên pod/deployment cần restart.", "command_restart")

    name = m.group(1)
    ns_m = _NS_IN_Q.search(question)
    hint_ns, hint_wl = _hints_from_question(question)
    ns = namespace or (ns_m.group(1) if ns_m else None) or hint_ns
    if not ns:
        # try from recent incident
        inc = await resolve_incident(
            session, question=question, namespace=None, incident_ref=None
        )
        ns = inc.namespace if inc else None
    if not ns:
        return _empty_response(
            f"Cần namespace để restart `{name}`. Ví dụ: restart pod {name} in npd-banking",
            "command_restart",
            recommendation="Specify namespace",
        )

    # If looks like a pod (has hash suffix), resolve deployment
    target = name
    if re.search(r"-[a-z0-9]{4,10}-[a-z0-9]{5}$", name) or name.count("-") >= 2:
        dep = await resolve_deployment(ns, name)
        if dep:
            target = dep

    # Prefer hint workload if name was generic "transfer"
    if hint_wl and name.lower() in {"transfer", "payment", "auth", "account"}:
        target = hint_wl

    incident = await resolve_incident(
        session, question=question, namespace=ns, incident_ref=None
    )
    incident_id = incident.external_id if incident else "CHAT-CMD"

    drafts = [
        {
            "incident_id": incident_id,
            "action": "restart-deployment",
            "namespace": ns,
            "target": target,
            "parameters": {},
            "reason": f"Operator chat command: {question[:160]}",
            "requested_by": "chat-operator",
        }
    ]
    created = await create_pending_remediations(drafts)
    ok = [c for c in created if c.get("ok")]
    answer = (
        f"Đã tạo pending remediation: restart-deployment `{ns}/{target}`. "
        f"Chưa thực thi — cần approve qua remediation API/console. "
        f"Created: {ok or created}"
    )
    return _empty_response(
        answer,
        "command_restart",
        recommendation="Approve the pending remediation to execute the restart.",
        remediations=created,
        nba={"remediations": created, "source": "chat-command"},
        incident={
            "id": str(incident.id) if incident else None,
            "external_id": incident_id,
            "title": incident.title if incident else "chat-command",
            "namespace": ns,
            "workload": target,
            "status": incident.status.value if incident else "n/a",
        }
        if ns
        else None,
        model="command",
    )


async def handle_chat(
    session: AsyncSession,
    *,
    question: str,
    namespace: str | None,
    incident_ref: str | None,
    auto_analyze: bool,
    session_id: str | None = None,
) -> dict[str, Any]:
    sid = session_id or new_session_id()
    history = await load_session_history(session, sid, limit=10) if session_id else []
    intent = detect_intent(question)

    if intent == "command_restart":
        result = await _handle_restart_command(session, question=question, namespace=namespace)
        return await _finalize_chat(
            session, session_id=sid, question=question, namespace=namespace, result=result
        )

    if intent == "ops_query":
        hint_ns, _ = _hints_from_question(question)
        ns = namespace or hint_ns
        ops = await fetch_ops_context(question, namespace=ns)
        incidents_brief = await recent_incidents_brief(session, namespace=ns)
        ops["recent_incidents"] = incidents_brief
        answer, evidence, recommendation = _ops_fallback_brief(question, ops)
        synthesized = await _synthesize_bounded(
            question=question,
            incident=None,
            rca={},
            remediations=[],
            ops_payload=ops,
            recent_incidents=incidents_brief,
            conversation_history=history,
        )
        model = "template"
        if synthesized:
            answer, evidence, recommendation, model = synthesized
        facts = ops.get("facts") or {}
        summary = ops.get("summary") or {}
        result = _empty_response(
            answer,
            "ops_query",
            evidence=evidence,
            recommendation=recommendation,
            ops_snapshot={
                "mode": "platform_context",
                "summary": summary,
                "metrics_source": facts.get("metrics_source"),
                "top_cpu_pods": facts.get("top_cpu_pods"),
                "top_memory_pods": facts.get("top_memory_pods"),
                "node_usage": facts.get("node_usage"),
                "counts": summary.get("counts"),
                "highlights": summary.get("highlights"),
                "warnings": ops.get("warnings"),
            },
            model=model,
        )
        return await _finalize_chat(
            session,
            session_id=sid,
            question=question,
            namespace=ns,
            result=result,
            ops=ops,
        )

    # investigate — bind to incident / RCA
    incident = await resolve_incident(
        session, question=question, namespace=namespace, incident_ref=incident_ref
    )
    if not incident:
        ops = await fetch_ops_context(question, namespace=namespace)
        incidents_brief = await recent_incidents_brief(session, namespace=namespace)
        answer, evidence, recommendation = _ops_fallback_brief(question, ops)
        synthesized = await _synthesize_bounded(
            question=question,
            incident=None,
            rca={},
            remediations=[],
            ops_payload=ops,
            recent_incidents=incidents_brief,
            conversation_history=history,
        )
        model = "template"
        if synthesized:
            answer, evidence, recommendation, model = synthesized
        result = _empty_response(
            answer,
            "ops_query",
            evidence=evidence,
            recommendation=recommendation,
            ops_snapshot={"mode": "platform_context", "summary": ops.get("summary")},
            model=model,
        )
        return await _finalize_chat(
            session,
            session_id=sid,
            question=question,
            namespace=namespace,
            result=result,
            ops=ops,
        )

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

    synthesized = await _synthesize_bounded(
        question=question,
        incident=incident,
        rca=rca,
        remediations=remediations,
        conversation_history=history,
    )
    if synthesized:
        answer, evidence, recommendation, model = synthesized
    else:
        answer, evidence, recommendation = _template_answer(incident=incident, rca=rca)
        model = "template"

    impact = rca.get("impact_scope")
    if isinstance(impact, dict):
        impact_scope = impact
    else:
        impact_scope = {
            "namespaces": [incident.namespace] if incident.namespace else [],
            "workloads": [incident.workload] if incident.workload else [],
            "pods": [],
            "nodes": [],
            "blast_radius": "service" if incident.workload else "namespace",
        }

    result = {
        "intent": intent,
        "answer": answer,
        "evidence": evidence,
        "recommendation": recommendation,
        "suggested_followups": [],
        "symptom": rca.get("symptom"),
        "symptom_confidence": rca.get("symptom_confidence"),
        "probable_root_cause": rca.get("probable_root_cause"),
        "root_cause_confidence": rca.get("root_cause_confidence"),
        "confidence": rca.get("confidence"),
        "error_subtype": rca.get("error_subtype"),
        "impact_scope": impact_scope,
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
        "ops_snapshot": None,
        "model": model,
    }
    return await _finalize_chat(
        session,
        session_id=sid,
        question=question,
        namespace=namespace or incident.namespace,
        result=result,
    )

"""Phase 6 helpers: follow-up suggestions + chat turn persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_api.models import ChatTurn


async def load_session_history(
    session: AsyncSession, session_id: str, *, limit: int = 10
) -> list[dict[str, str]]:
    """Last N turns as OpenAI-style messages (user/assistant)."""
    result = await session.execute(
        select(ChatTurn)
        .where(ChatTurn.session_id == session_id)
        .order_by(ChatTurn.created_at.desc())
        .limit(limit)
    )
    rows = list(reversed(result.scalars().all()))
    return [{"role": r.role, "content": r.content[:1500]} for r in rows]


async def save_turn(
    session: AsyncSession,
    *,
    session_id: str,
    role: str,
    content: str,
    namespace: str | None = None,
    intent: str | None = None,
    model: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    session.add(
        ChatTurn(
            session_id=session_id,
            role=role,
            content=content[:8000],
            namespace=namespace,
            intent=intent,
            model=model,
            meta=meta or {},
        )
    )
    await session.commit()


def suggest_followups(
    *,
    intent: str,
    question: str,
    namespace: str | None,
    ops: dict[str, Any] | None = None,
    incident: dict[str, Any] | None = None,
) -> list[str]:
    """Rule-based next questions — reliable for small local LLMs."""
    ns = namespace or "npd-banking"
    facts = (ops or {}).get("facts") or {}
    summary = (ops or {}).get("summary") or {}
    counts = summary.get("counts") or {}
    out: list[str] = []

    if intent == "command_restart":
        out.extend(
            [
                "Có pod nào CrashLoopBackOff không?",
                f"Deployment nào trong {ns} chưa ready?",
                "Có điều gì đáng lưu ý không?",
            ]
        )
        return out[:4]

    if intent == "investigate" and incident:
        wl = incident.get("workload") or "the service"
        out.extend(
            [
                f"Impact scope của {wl} là gì?",
                "Remediation pending nào có thể approve?",
                f"Pods nào đang cao tải trong {incident.get('namespace') or ns}?",
            ]
        )
        return out[:4]

    # ops_query defaults
    if (counts.get("crashloop") or 0) > 0 or facts.get("crashloop_pods"):
        out.append("Liệt kê pod CrashLoopBackOff và waiting.message")
    if (counts.get("imagepull") or 0) > 0:
        out.append("Pod nào ImagePullBackOff và message là gì?")
    if (counts.get("hpa_at_max") or 0) > 0:
        out.append("HPA nào đang kẹt max replicas?")
    if (counts.get("pvc_not_bound") or 0) > 0:
        out.append("PVC nào chưa Bound?")
    if (counts.get("nodes_disk_pressure") or 0) > 0 or (counts.get("node_fs_hot") or 0) > 0:
        out.append("Node nào đang đầy disk?")
    if (counts.get("pvc_hot") or 0) > 0:
        out.append("PVC nào dùng trên 80%?")
    if facts.get("top_cpu_pods"):
        out.append("Node nào đang dùng nhiều CPU?")
    out.append(f"Deployment nào trong {ns} chưa ready?")
    out.append("Có điều gì đáng lưu ý không?")
    # de-dupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for q in out:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq[:5]

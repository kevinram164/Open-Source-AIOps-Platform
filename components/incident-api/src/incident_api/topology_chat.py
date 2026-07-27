"""Phase 7C — topology Q&A + Mermaid from graph edges (deterministic)."""

from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

from incident_api.config import settings

log = structlog.get_logger()

_TOPOLOGY_INTENT = re.compile(
    r"(?:vẽ|ve|draw|show|hiển\s*thị|hien\s*thi|sơ\s*đồ|so\s*do|diagram|mermaid|"
    r"topology|topo|dependency|dependencies|luồng|luong|flow|blast\s*radius|"
    r"service\s*map|ai\s*gọi\s*ai|quan\s*hệ\s*dịch\s*vụ)",
    re.I,
)

_CLUSTER_SCOPE = re.compile(
    r"(?:cả\s*cụm|ca\s*cum|toàn\s*cluster|toan\s*cluster|whole\s*cluster|"
    r"entire\s*cluster|\bocp\b.*(?:map|diagram|sơ\s*đồ)|\ball\s*namespaces?\b)",
    re.I,
)

# App-level centers (broader than single-service hints)
_APP_CENTERS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bmovie\b|cinehome|phim|npd-movie", re.I), "npd-movie", "movie-api"),
    (re.compile(r"\bbanking\b|\bbank\b|npd-banking|payment", re.I), "npd-banking", "api-producer"),
    (re.compile(r"\baiops\b|incident-api|rca-agent", re.I), "aiops-core", "incident-api"),
]


def is_topology_question(question: str) -> bool:
    return bool(_TOPOLOGY_INTENT.search(question or ""))


def is_cluster_wide_request(question: str) -> bool:
    return bool(_CLUSTER_SCOPE.search(question or ""))


def resolve_topology_center(
    question: str,
    *,
    namespace: str | None = None,
    service_hints: list[tuple[re.Pattern[str], str, str]] | None = None,
) -> tuple[str | None, str | None]:
    """Return (namespace, workload) for topology center."""
    q = question or ""
    if service_hints:
        for pat, ns, wl in service_hints:
            if pat.search(q):
                return ns, wl
    for pat, ns, wl in _APP_CENTERS:
        if pat.search(q):
            return ns, wl
    if namespace:
        # namespace-only: pick a known default center
        ns = namespace.lower()
        for _, app_ns, wl in _APP_CENTERS:
            if app_ns == ns:
                return app_ns, wl
        return namespace, None
    return None, None


def _mid(ref: str) -> str:
    """Mermaid-safe node id."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", ref)[:64] or "node"


def _label(ref: str) -> str:
    text = ref.replace('"', "'")
    if "/" in text:
        return text
    return text


def topology_to_mermaid(topo: dict[str, Any]) -> str:
    """Build flowchart LR from topology edges / neighbors."""
    center = topo.get("center") or {}
    cid = center.get("id") or f"{center.get('namespace') or ''}/{center.get('name') or 'center'}"
    lines = ["flowchart LR"]
    seen_nodes = {cid}
    lines.append(f'  {_mid(cid)}["{_label(cid)}"]:::center')

    edges = list(topo.get("edges") or [])
    if not edges:
        # synthesize from neighbors
        for n in topo.get("upstream") or []:
            nid = n.get("id") or f"{n.get('namespace')}/{n.get('name')}"
            edges.append({"from": nid, "to": cid, "kind": n.get("kind") or "dep"})
        for n in topo.get("downstream") or []:
            nid = n.get("id") or f"{n.get('namespace')}/{n.get('name')}"
            edges.append({"from": cid, "to": nid, "kind": n.get("kind") or "dep"})

    for e in edges[:40]:
        frm = str(e.get("from") or "")
        to = str(e.get("to") or "")
        if not frm or not to:
            continue
        for ref in (frm, to):
            if ref not in seen_nodes:
                seen_nodes.add(ref)
                lines.append(f'  {_mid(ref)}["{_label(ref)}"]')
        kind = e.get("kind") or ""
        if kind and kind not in ("dep", "ebpf"):
            lines.append(f"  {_mid(frm)} -->|{kind}| {_mid(to)}")
        else:
            lines.append(f"  {_mid(frm)} --> {_mid(to)}")

    lines.append("  classDef center fill:#3ddc97,stroke:#0e1626,color:#060a12")
    return "\n".join(lines)


async def fetch_topology(
    namespace: str | None,
    workload: str | None,
    *,
    hops: int = 2,
) -> dict[str, Any]:
    url = settings.rca_agent_url.rstrip("/") + "/api/v1/topology"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            url,
            params={
                "namespace": namespace or "",
                "workload": workload or "",
                "hops": hops,
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"rca-agent topology HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()


def format_topology_answer(topo: dict[str, Any], *, mermaid: str) -> tuple[str, list[str]]:
    center = topo.get("center") or {}
    cid = center.get("id") or f"{center.get('namespace')}/{center.get('name')}"
    src = topo.get("source") or "unknown"
    up = topo.get("upstream") or []
    down = topo.get("downstream") or []
    answer = (
        f"Service map for **{cid}** (source=`{src}`, hops≤2).\n\n"
        f"- Upstream (callers): {len(up)}\n"
        f"- Downstream (deps): {len(down)}\n\n"
        f"```mermaid\n{mermaid}\n```"
    )
    evidence = [f"Topo center={cid} source={src}"]
    for n in up[:5]:
        evidence.append(f"upstream: {n.get('namespace')}/{n.get('name')}")
    for n in down[:5]:
        evidence.append(f"downstream: {n.get('namespace')}/{n.get('name')}")
    return answer, evidence

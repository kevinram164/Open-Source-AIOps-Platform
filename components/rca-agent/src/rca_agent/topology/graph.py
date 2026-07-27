"""Phase 7 — service dependency topology.

Sources (priority):
1. Coroot CE service map / AppMap (live eBPF) — Phase 7B
2. Static demo adjacency (banking / movie / aiops) — fallback
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from rca_agent.config import settings

log = structlog.get_logger()

# ns/name → neighbors (undirected for blast-radius; directed edges stored separately)
_BANKING_EDGES: list[tuple[str, str, str]] = [
    ("npd-banking/frontend", "npd-banking/api-producer", "http"),
    ("npd-banking/api-producer", "npd-banking/auth-service", "http"),
    ("npd-banking/api-producer", "npd-banking/account-service", "http"),
    ("npd-banking/api-producer", "npd-banking/transfer-service", "http"),
    ("npd-banking/transfer-service", "npd-banking/account-service", "http"),
    ("npd-banking/transfer-service", "npd-banking/notification-service", "http"),
    ("npd-banking/account-service", "npd-banking/postgres", "db"),
    ("npd-banking/auth-service", "npd-banking/redis-ha", "cache"),
]

_MOVIE_EDGES: list[tuple[str, str, str]] = [
    ("npd-movie/movie-web", "npd-movie/movie-api", "http"),
    ("npd-movie/movie-api", "npd-movie/media-worker", "queue"),
    ("npd-movie/movie-api", "postgres/postgres", "db"),
    ("npd-movie/media-worker", "postgres/postgres", "db"),
    ("npd-movie/movie-api", "redis/redis-ha", "cache"),
    ("npd-movie/media-worker", "redis/redis-ha", "cache"),
    ("npd-movie/movie-api", "minio/minio", "s3"),
    ("npd-movie/media-worker", "minio/minio", "s3"),
]

_AIOPS_EDGES: list[tuple[str, str, str]] = [
    ("aiops-core/aiops-console", "aiops-core/incident-api", "http"),
    ("aiops-core/incident-api", "aiops-core/rca-agent", "http"),
    ("aiops-core/incident-api", "aiops-automation/remediation-controller", "http"),
    ("aiops-core/incident-api", "aiops-core/ollama", "http"),
    ("aiops-core/rca-agent", "aiops-core/ollama", "http"),
    ("aiops-core/rca-agent", "observability/coroot-coroot", "http"),
]

_ALL_EDGES = _BANKING_EDGES + _MOVIE_EDGES + _AIOPS_EDGES

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_S = 90.0


def _norm_node(ref: str) -> dict[str, str]:
    if "/" in ref:
        ns, name = ref.split("/", 1)
    else:
        ns, name = "", ref
    return {"namespace": ns, "name": name, "id": f"{ns}/{name}" if ns else name}


def _neighbors_static(center: str, hops: int = 2) -> dict[str, Any]:
    """BFS undirected over static edges."""
    adj: dict[str, set[str]] = {}
    edge_meta: dict[tuple[str, str], str] = {}
    for frm, to, kind in _ALL_EDGES:
        adj.setdefault(frm, set()).add(to)
        adj.setdefault(to, set()).add(frm)
        edge_meta[(frm, to)] = kind
        edge_meta[(to, frm)] = kind

    center_l = center.lower()
    if center_l not in adj:
        for node in list(adj.keys()):
            if node.endswith("/" + center_l.split("/")[-1]):
                center_l = node
                break

    upstream: list[dict[str, Any]] = []
    downstream: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    seen = {center_l}
    frontier = [(center_l, 0, "self")]

    out_from = {to for frm, to, _ in _ALL_EDGES if frm.lower() == center_l}
    in_to = {frm for frm, to, _ in _ALL_EDGES if to.lower() == center_l}

    while frontier:
        node, dist, _ = frontier.pop(0)
        if dist >= hops:
            continue
        for nb in sorted(adj.get(node, set())):
            if nb in seen:
                continue
            seen.add(nb)
            nd = dist + 1
            kind = edge_meta.get((node, nb), "dep")
            entry = {**_norm_node(nb), "hops": nd, "kind": kind}
            if nd == 1 and nb in in_to and nb not in out_from:
                upstream.append(entry)
            elif nd == 1 and nb in out_from:
                downstream.append(entry)
            elif nb in in_to or any(e["id"] == _norm_node(nb)["id"] for e in upstream):
                upstream.append(entry)
            else:
                downstream.append(entry)
            edges.append({"from": node, "to": nb, "kind": kind})
            frontier.append((nb, nd, "walk"))

    return {
        "center": _norm_node(center_l),
        "upstream": upstream,
        "downstream": downstream,
        "edges": edges,
        "source": "static",
    }


def _merge_neighbors(primary: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {(n.get("id") or n.get("name") or "").lower() for n in primary}
    out = list(primary)
    for n in extra:
        key = (n.get("id") or n.get("name") or "").lower()
        if key and key not in seen:
            seen.add(key)
            out.append(n)
    return out


def get_topology(
    namespace: str | None,
    workload: str | None,
    *,
    hops: int = 2,
) -> dict[str, Any]:
    """Sync topology lookup (static only) with TTL cache."""
    if not workload and not namespace:
        return {
            "center": {"namespace": "", "name": "", "id": ""},
            "upstream": [],
            "downstream": [],
            "edges": [],
            "source": "empty",
        }

    cache_key = f"static|{namespace}|{workload}|{hops}"
    now = time.monotonic()
    hit = _CACHE.get(cache_key)
    if hit and now - hit[0] < _CACHE_TTL_S:
        return hit[1]

    center = f"{namespace}/{workload}" if namespace and workload else (workload or namespace or "")
    data = _neighbors_static(center, hops=hops)
    if not data["upstream"] and not data["downstream"] and namespace and workload:
        data["source"] = "static-miss"

    _CACHE[cache_key] = (now, data)
    return data


async def get_topology_async(
    namespace: str | None,
    workload: str | None,
    *,
    hops: int = 2,
) -> dict[str, Any]:
    """Prefer Coroot live map; merge/fallback to static lab adjacency."""
    cache_key = f"async|{namespace}|{workload}|{hops}"
    now = time.monotonic()
    hit = _CACHE.get(cache_key)
    if hit and now - hit[0] < _CACHE_TTL_S:
        return hit[1]

    static = get_topology(namespace, workload, hops=hops)
    coroot_topo: dict[str, Any] | None = None
    try:
        from rca_agent.topology.coroot_client import CorootClient

        coroot_topo = await CorootClient().fetch_topology(namespace, workload, hops=hops)
    except Exception as exc:  # noqa: BLE001
        log.warning("coroot_topology_error", error=str(exc))

    if not coroot_topo or coroot_topo.get("source") in {
        "coroot-noproject",
        "coroot-miss",
        None,
    }:
        data = {**static}
        if coroot_topo and coroot_topo.get("coroot"):
            data["coroot"] = coroot_topo["coroot"]
            if static.get("upstream") or static.get("downstream"):
                data["source"] = "static+coroot-fallback"
            else:
                data["source"] = coroot_topo.get("source") or "static"
        _CACHE[cache_key] = (now, data)
        return data

    # Coroot hit with (possibly empty) neighbors — merge static extras for lab demos
    data = {
        "center": coroot_topo.get("center") or static.get("center"),
        "upstream": _merge_neighbors(
            list(coroot_topo.get("upstream") or []),
            list(static.get("upstream") or []),
        ),
        "downstream": _merge_neighbors(
            list(coroot_topo.get("downstream") or []),
            list(static.get("downstream") or []),
        ),
        "edges": list(coroot_topo.get("edges") or []) + list(static.get("edges") or []),
        "source": "coroot+static" if (static.get("upstream") or static.get("downstream")) else "coroot",
        "coroot": coroot_topo.get("coroot"),
    }
    _CACHE[cache_key] = (now, data)
    return data


def topology_evidence_lines(topo: dict[str, Any], *, limit: int = 8) -> list[str]:
    lines: list[str] = []
    center = topo.get("center") or {}
    cid = center.get("id") or f"{center.get('namespace')}/{center.get('name')}"
    src = topo.get("source", "unknown")
    lines.append(f"Topo center={cid} source={src}")
    for label, key in (("upstream", "upstream"), ("downstream", "downstream")):
        for n in (topo.get(key) or [])[:4]:
            lines.append(
                f"Topo {label}: {n.get('namespace')}/{n.get('name')} "
                f"(hops={n.get('hops')}, kind={n.get('kind')})"
            )
    coroot = topo.get("coroot") or {}
    if coroot.get("coroot_reachable"):
        via = coroot.get("via") or "api"
        lines.append(f"Coroot map via={via} project={coroot.get('project_id') or 'n/a'}")
    return lines[:limit]


def related_workloads(
    ns_a: str | None,
    wl_a: str | None,
    ns_b: str | None,
    wl_b: str | None,
    *,
    hops: int = 2,
) -> bool:
    """True if A and B are the same node or within hops on the static graph."""
    if not wl_a or not wl_b:
        return bool(ns_a and ns_a == ns_b and not wl_a and not wl_b)
    if ns_a == ns_b and wl_a == wl_b:
        return True
    topo = get_topology(ns_a, wl_a, hops=hops)
    target = f"{ns_b}/{wl_b}".lower() if ns_b else wl_b.lower()
    for bucket in ("upstream", "downstream"):
        for n in topo.get(bucket) or []:
            nid = (n.get("id") or f"{n.get('namespace')}/{n.get('name')}").lower()
            if nid == target or n.get("name") == wl_b:
                return True
    topo_b = get_topology(ns_b, wl_b, hops=hops)
    for bucket in ("upstream", "downstream"):
        for n in topo_b.get(bucket) or []:
            if n.get("name") == wl_a and (not ns_a or n.get("namespace") == ns_a):
                return True
    return False


async def related_workloads_async(
    ns_a: str | None,
    wl_a: str | None,
    ns_b: str | None,
    wl_b: str | None,
    *,
    hops: int = 2,
) -> bool:
    """Same as related_workloads but uses Coroot+static async topology."""
    if not wl_a or not wl_b:
        return bool(ns_a and ns_a == ns_b and not wl_a and not wl_b)
    if ns_a == ns_b and wl_a == wl_b:
        return True
    if related_workloads(ns_a, wl_a, ns_b, wl_b, hops=hops):
        return True
    topo = await get_topology_async(ns_a, wl_a, hops=hops)
    for bucket in ("upstream", "downstream"):
        for n in topo.get(bucket) or []:
            if n.get("name") == wl_b and (not ns_b or n.get("namespace") == ns_b or not n.get("namespace")):
                return True
    return False

"""Coroot CE topology client — live service map (eBPF).

Uses classic UI REST (not MCP/OAuth):
  GET /api/user                         → project id map
  GET /api/project/{id}/overview/map    → fleet service map
  GET /api/project/{id}/app/{app_id}    → app_map clients/dependencies

Auth (optional, lab often anonymous):
  POST /api/login  {email, password, action: login} → coroot_session cookie
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import structlog

from rca_agent.config import settings

log = structlog.get_logger()

# Coroot: upstreams = deps this app calls; downstreams = clients that call this app.
# Our blast-radius vocabulary: upstream = callers, downstream = dependencies.


def _parse_app_id(raw: Any) -> tuple[str, str, str]:
    """Return (namespace, kind, name) from Coroot application id."""
    if raw is None:
        return "", "", ""
    if isinstance(raw, dict):
        return (
            str(raw.get("Namespace") or raw.get("namespace") or ""),
            str(raw.get("Kind") or raw.get("kind") or ""),
            str(raw.get("Name") or raw.get("name") or ""),
        )
    text = str(raw)
    parts = text.split(":")
    if len(parts) >= 4:
        # cluster:namespace:kind:name
        return parts[1], parts[2], ":".join(parts[3:])
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if "/" in text:
        ns, name = text.split("/", 1)
        return ns, "", name
    return "", "", text


def _node_from_id(raw: Any, *, hops: int = 1, kind: str = "ebpf") -> dict[str, Any]:
    ns, _k, name = _parse_app_id(raw)
    nid = f"{ns}/{name}" if ns and name else (name or str(raw))
    return {
        "namespace": ns,
        "name": name,
        "id": nid,
        "hops": hops,
        "kind": kind,
        "coroot_id": str(raw) if not isinstance(raw, dict) else raw.get("id") or nid,
    }


def _unwrap_data(payload: Any) -> Any:
    """Coroot often wraps views as {data: ...} or {context, data}."""
    if not isinstance(payload, dict):
        return payload
    if "data" in payload and payload["data"] is not None:
        return payload["data"]
    return payload


def _projects_from_user(payload: Any) -> list[str]:
    data = _unwrap_data(payload)
    if not isinstance(data, dict):
        return []
    # projects may be {name: id} or list
    projects = data.get("projects") or data.get("Projects") or {}
    if isinstance(projects, dict):
        return [str(v) for v in projects.values() if v] or [str(k) for k in projects.keys()]
    if isinstance(projects, list):
        out: list[str] = []
        for p in projects:
            if isinstance(p, dict):
                out.append(str(p.get("id") or p.get("Id") or ""))
            else:
                out.append(str(p))
        return [x for x in out if x]
    return []


class CorootClient:
    def __init__(self) -> None:
        self.base = (settings.coroot_url or "").rstrip("/")
        self.project_id = (settings.coroot_project_id or "").strip()
        self.email = (settings.coroot_email or "").strip()
        self.password = settings.coroot_password or ""
        self._cookies: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.base) and settings.coroot_topology_enabled

    async def _client(self):
        import httpx

        return httpx.AsyncClient(
            timeout=12.0,
            follow_redirects=True,
            cookies=self._cookies or None,
        )

    async def _ensure_session(self, client) -> None:
        if self._cookies or not (self.email and self.password):
            return
        try:
            resp = await client.post(
                f"{self.base}/api/login",
                json={"email": self.email, "password": self.password, "action": "login"},
            )
            cookie = resp.cookies.get("coroot_session")
            if cookie:
                self._cookies["coroot_session"] = cookie
                client.cookies.set("coroot_session", cookie)
        except Exception as exc:  # noqa: BLE001
            log.debug("coroot_login_failed", error=str(exc))

    async def _get_json(self, client, path: str) -> Any | None:
        try:
            resp = await client.get(f"{self.base}{path}")
            if resp.status_code in (401, 403):
                await self._ensure_session(client)
                resp = await client.get(f"{self.base}{path}")
            if resp.status_code >= 400:
                log.debug("coroot_http_error", path=path, status=resp.status_code)
                return None
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            log.debug("coroot_get_failed", path=path, error=str(exc))
            return None

    async def resolve_project_id(self, client) -> str | None:
        if self.project_id:
            return self.project_id
        user = await self._get_json(client, "/api/user")
        ids = _projects_from_user(user or {})
        if ids:
            self.project_id = ids[0]
            return self.project_id
        # Some CE installs expose empty path project create; try common probe
        return None

    def _match_app(self, apps: list[dict[str, Any]], namespace: str | None, workload: str | None) -> dict[str, Any] | None:
        if not workload:
            return None
        wl = workload.lower()
        ns = (namespace or "").lower()
        scored: list[tuple[int, dict[str, Any]]] = []
        for app in apps:
            app_id = app.get("id") or app.get("Id")
            a_ns, _kind, a_name = _parse_app_id(app_id)
            score = 0
            if a_name.lower() == wl:
                score += 100
            elif wl in a_name.lower():
                score += 40
            if ns and a_ns.lower() == ns:
                score += 30
            elif ns and a_ns.lower() == ns.replace("_", "-"):
                score += 20
            if score:
                scored.append((score, app))
        if not scored:
            return None
        scored.sort(key=lambda x: -x[0])
        return scored[0][1]

    def _topology_from_service_map(
        self,
        apps: list[dict[str, Any]],
        namespace: str | None,
        workload: str | None,
        *,
        hops: int,
    ) -> dict[str, Any] | None:
        """BFS on overview/map: Coroot upstreams=deps, downstreams=callers."""
        by_id: dict[str, dict[str, Any]] = {}
        for app in apps:
            raw_id = app.get("id") or app.get("Id")
            if raw_id is None:
                continue
            by_id[str(raw_id)] = app
            # also index without cluster prefix
            ns, kind, name = _parse_app_id(raw_id)
            by_id.setdefault(f"{ns}:{kind}:{name}", app)

        center_app = self._match_app(apps, namespace, workload)
        if not center_app:
            return None
        center_raw = center_app.get("id") or center_app.get("Id")
        center_ns, _ck, center_name = _parse_app_id(center_raw)
        center_key = str(center_raw)

        upstream: list[dict[str, Any]] = []  # callers
        downstream: list[dict[str, Any]] = []  # deps
        edges: list[dict[str, str]] = []
        seen = {center_key}
        # frontier: (app_id_str, hops_from_center, direction_bias)
        frontier: list[tuple[str, int]] = [(center_key, 0)]

        while frontier:
            cur_id, dist = frontier.pop(0)
            if dist >= hops:
                continue
            app = by_id.get(cur_id)
            if not app:
                continue
            # deps this app calls → our downstream
            for link in app.get("upstreams") or app.get("Upstreams") or []:
                lid = link.get("id") if isinstance(link, dict) else link
                lid_s = str(lid)
                if lid_s in seen:
                    continue
                seen.add(lid_s)
                node = _node_from_id(lid, hops=dist + 1, kind="ebpf")
                if dist == 0:
                    downstream.append(node)
                else:
                    # further hops: keep in downstream bucket if walking deps
                    downstream.append(node)
                edges.append({"from": cur_id, "to": lid_s, "kind": "ebpf"})
                frontier.append((lid_s, dist + 1))
            # clients → our upstream
            for link in app.get("downstreams") or app.get("Downstreams") or []:
                lid = link.get("id") if isinstance(link, dict) else link
                lid_s = str(lid)
                if lid_s in seen:
                    continue
                seen.add(lid_s)
                node = _node_from_id(lid, hops=dist + 1, kind="ebpf")
                upstream.append(node)
                edges.append({"from": lid_s, "to": cur_id, "kind": "ebpf"})
                frontier.append((lid_s, dist + 1))

        return {
            "center": {
                "namespace": center_ns,
                "name": center_name,
                "id": f"{center_ns}/{center_name}" if center_ns else center_name,
            },
            "upstream": upstream,
            "downstream": downstream,
            "edges": edges,
            "source": "coroot",
            "coroot": {
                "coroot_reachable": True,
                "project_id": self.project_id,
                "app_id": center_key,
                "via": "overview/map",
            },
        }

    def _topology_from_app_map(
        self,
        payload: Any,
        namespace: str | None,
        workload: str | None,
    ) -> dict[str, Any] | None:
        data = _unwrap_data(payload)
        if not isinstance(data, dict):
            return None
        app_map = data.get("app_map") or data.get("appMap") or data
        if not isinstance(app_map, dict):
            return None
        app = app_map.get("application") or {}
        app_id = app.get("id") if isinstance(app, dict) else None
        if not app_id and workload:
            # still use requested center
            center_ns, center_name = namespace or "", workload
        else:
            center_ns, _k, center_name = _parse_app_id(app_id)

        upstream = [
            _node_from_id(c.get("id") if isinstance(c, dict) else c, hops=1, kind="ebpf")
            for c in (app_map.get("clients") or [])
        ]
        downstream = [
            _node_from_id(d.get("id") if isinstance(d, dict) else d, hops=1, kind="ebpf")
            for d in (app_map.get("dependencies") or [])
        ]
        edges: list[dict[str, str]] = []
        cid = f"{center_ns}/{center_name}" if center_ns else center_name
        for n in upstream:
            edges.append({"from": n["id"], "to": cid, "kind": "ebpf"})
        for n in downstream:
            edges.append({"from": cid, "to": n["id"], "kind": "ebpf"})

        if not upstream and not downstream and not app_id:
            return None

        return {
            "center": {"namespace": center_ns, "name": center_name, "id": cid},
            "upstream": upstream,
            "downstream": downstream,
            "edges": edges,
            "source": "coroot",
            "coroot": {
                "coroot_reachable": True,
                "project_id": self.project_id,
                "app_id": str(app_id) if app_id else None,
                "via": "app_map",
            },
        }

    async def fetch_topology(
        self,
        namespace: str | None,
        workload: str | None,
        *,
        hops: int = 2,
    ) -> dict[str, Any] | None:
        if not self.enabled or not workload:
            return None

        async with await self._client() as client:
            await self._ensure_session(client)
            project = await self.resolve_project_id(client)
            if not project:
                log.info("coroot_no_project", hint="set COROOT_PROJECT_ID from Coroot UI URL")
                return {
                    "center": {
                        "namespace": namespace or "",
                        "name": workload,
                        "id": f"{namespace}/{workload}" if namespace else workload,
                    },
                    "upstream": [],
                    "downstream": [],
                    "edges": [],
                    "source": "coroot-noproject",
                    "coroot": {"coroot_reachable": True, "error": "no project id"},
                }

            # 1) Prefer fleet map (multi-hop)
            overview = await self._get_json(client, f"/api/project/{project}/overview/map")
            data = _unwrap_data(overview) if overview is not None else None
            apps: list[dict[str, Any]] = []
            if isinstance(data, dict):
                apps = data.get("map") or data.get("Map") or []
            elif isinstance(data, list):
                apps = data
            if apps:
                topo = self._topology_from_service_map(apps, namespace, workload, hops=hops)
                if topo and (topo["upstream"] or topo["downstream"] or topo.get("center")):
                    # Accept even if no neighbors (app exists but isolated)
                    matched = self._match_app(apps, namespace, workload)
                    if matched:
                        log.info(
                            "coroot_topology_ok",
                            via="overview/map",
                            workload=workload,
                            up=len(topo["upstream"]),
                            down=len(topo["downstream"]),
                        )
                        return topo

            # 2) Fallback: single-app AppMap (1 hop)
            candidates = []
            if namespace:
                for kind in ("Deployment", "StatefulSet", "DaemonSet", "Service"):
                    candidates.append(f"{namespace}:{kind}:{workload}")
                    candidates.append(f"_:{namespace}:{kind}:{workload}")
            candidates.append(workload)

            for cand in candidates:
                encoded = quote(cand, safe="")
                app_payload = await self._get_json(
                    client, f"/api/project/{project}/app/{encoded}"
                )
                if not app_payload:
                    continue
                topo = self._topology_from_app_map(app_payload, namespace, workload)
                if topo:
                    log.info(
                        "coroot_topology_ok",
                        via="app_map",
                        app=cand,
                        up=len(topo["upstream"]),
                        down=len(topo["downstream"]),
                    )
                    return topo

            log.info("coroot_topology_miss", namespace=namespace, workload=workload)
            return {
                "center": {
                    "namespace": namespace or "",
                    "name": workload,
                    "id": f"{namespace}/{workload}" if namespace else workload,
                },
                "upstream": [],
                "downstream": [],
                "edges": [],
                "source": "coroot-miss",
                "coroot": {
                    "coroot_reachable": True,
                    "project_id": project,
                    "error": "app not found in Coroot map",
                },
            }

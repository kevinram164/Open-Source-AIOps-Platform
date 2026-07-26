"""Per-PVC directory usage via `du` in a pod that mounts the claim.

On NFS/shared CSI, kubelet_volume_stats_* reports the whole share — not each PVC.
Measuring `du -sb <mountPath>` against PVC request size gives a usable per-claim %.
"""

from __future__ import annotations

import re
import shlex
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import structlog
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream

log = structlog.get_logger()

_SKIP_NS_PREFIX = ("openshift-", "kube-", "openshift")


def _core() -> client.CoreV1Api | None:
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        return client.CoreV1Api()
    except Exception as exc:  # noqa: BLE001
        log.warning("pvc_du_core_unavailable", error=str(exc))
        return None


def _parse_qty_bytes(qty: str | None) -> int | None:
    if not qty:
        return None
    s = str(qty).strip()
    m = re.fullmatch(r"(?i)(\d+(?:\.\d+)?)([KMGTP]i?)?", s)
    if not m:
        try:
            return int(float(s))
        except ValueError:
            return None
    n = float(m.group(1))
    unit = (m.group(2) or "").lower()
    mul = {
        "": 1,
        "k": 1000,
        "m": 1000**2,
        "g": 1000**3,
        "t": 1000**4,
        "p": 1000**5,
        "ki": 1024,
        "mi": 1024**2,
        "gi": 1024**3,
        "ti": 1024**4,
        "pi": 1024**5,
    }.get(unit)
    if mul is None:
        return None
    return int(n * mul)


def _fmt_bytes(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.2f}Gi"
    if n >= 1024**2:
        return f"{n / 1024**2:.0f}Mi"
    if n >= 1024:
        return f"{n / 1024:.0f}Ki"
    return f"{n}B"


def _find_mount(
    api: client.CoreV1Api, namespace: str, pvc_name: str
) -> tuple[str, str, str] | None:
    """Return (pod_name, container_name, mount_path) for a Running pod using the PVC."""
    try:
        pods = api.list_namespaced_pod(namespace).items
    except ApiException:
        return None
    for pod in pods:
        if (pod.status.phase if pod.status else None) != "Running":
            continue
        if not pod.spec or not pod.spec.volumes:
            continue
        vol_name = None
        for vol in pod.spec.volumes:
            pvc = vol.persistent_volume_claim
            if pvc and pvc.claim_name == pvc_name:
                vol_name = vol.name
                break
        if not vol_name:
            continue
        for c in pod.spec.containers or []:
            for vm in c.volume_mounts or []:
                if vm.name != vol_name:
                    continue
                path = vm.mount_path or ""
                if vm.sub_path:
                    path = path.rstrip("/") + "/" + vm.sub_path.lstrip("/")
                if path:
                    return pod.metadata.name, c.name, path
    return None


def _du_bytes(
    api: client.CoreV1Api,
    *,
    namespace: str,
    pod: str,
    container: str,
    path: str,
    timeout_s: int = 12,
) -> int | None:
    """Exec du in pod. Use websocket stream (_preload_content=False) — preload hits None.decode on OCP."""
    import time

    commands: list[list[str]] = [
        ["du", "-sb", path],
        ["/bin/sh", "-c", f"du -sb {shlex.quote(path)} 2>/dev/null | cut -f1"],
        ["/bin/bash", "-c", f"du -sb {shlex.quote(path)} 2>/dev/null | cut -f1"],
    ]
    last_err: str | None = None
    for cmd in commands:
        resp = None
        try:
            resp = stream(
                api.connect_get_namespaced_pod_exec,
                pod,
                namespace,
                command=cmd,
                container=container,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=False,
            )
            stdout_parts: list[str] = []
            deadline = time.time() + timeout_s
            while getattr(resp, "is_open", lambda: False)() and time.time() < deadline:
                resp.update(timeout=1)
                if resp.peek_stdout():
                    chunk = resp.read_stdout()
                    if chunk:
                        stdout_parts.append(chunk)
                if resp.peek_stderr():
                    _ = resp.read_stderr()
            try:
                if resp.peek_stdout():
                    chunk = resp.read_stdout()
                    if chunk:
                        stdout_parts.append(chunk)
            except Exception:  # noqa: BLE001
                pass
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass

            text = "".join(stdout_parts).strip()
            if not text:
                last_err = "empty_stdout"
                continue
            first = text.splitlines()[-1].split()[0]
            return int(first)
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            try:
                if resp is not None:
                    resp.close()
            except Exception:  # noqa: BLE001
                pass
            continue

    log.warning(
        "pvc_du_exec_failed",
        ns=namespace,
        pod=pod,
        path=path,
        error=last_err,
    )
    return None


def _measure_one(
    api: client.CoreV1Api, pvc: Any
) -> dict[str, Any] | None:
    ns = pvc.metadata.namespace
    name = pvc.metadata.name
    req = None
    try:
        req = pvc.spec.resources.requests.get("storage") if pvc.spec and pvc.spec.resources else None
    except Exception:  # noqa: BLE001
        req = None
    cap = _parse_qty_bytes(str(req) if req is not None else None)
    mount = _find_mount(api, ns, name)
    if not mount:
        return {
            "namespace": ns,
            "persistentvolumeclaim": name,
            "method": "du",
            "error": "no_running_pod_mount",
            "capacity_bytes": cap,
            "capacity_human": _fmt_bytes(cap) if cap else None,
            "request": str(req) if req else None,
        }
    pod, container, path = mount
    used = _du_bytes(api, namespace=ns, pod=pod, container=container, path=path)
    if used is None:
        return {
            "namespace": ns,
            "persistentvolumeclaim": name,
            "method": "du",
            "error": "du_failed",
            "pod": pod,
            "mount_path": path,
            "capacity_bytes": cap,
            "capacity_human": _fmt_bytes(cap) if cap else None,
            "request": str(req) if req else None,
        }
    pct = round(100.0 * used / cap, 1) if cap and cap > 0 else None
    return {
        "namespace": ns,
        "persistentvolumeclaim": name,
        "method": "du",
        "used_bytes": used,
        "used_human": _fmt_bytes(used),
        "capacity_bytes": cap,
        "capacity_human": _fmt_bytes(cap) if cap else None,
        "request": str(req) if req else None,
        "used_percent": pct,
        "pod": pod,
        "mount_path": path,
    }


def collect_pvc_usage_via_du(
    *,
    namespace: str | None = None,
    max_pvcs: int = 12,
    workers: int = 4,
) -> dict[str, Any]:
    """
    Per-PVC usage = du(mount) / PVC request size.

    Returns rows sorted by used_percent desc (then used_bytes).
    """
    out: dict[str, Any] = {"pvc_usage": [], "warnings": [], "source": "du"}
    api = _core()
    if not api:
        out["warnings"].append("core api unavailable for pvc du")
        return out

    try:
        if namespace:
            items = api.list_namespaced_persistent_volume_claim(namespace).items
        else:
            items = api.list_persistent_volume_claim_for_all_namespaces().items
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"list pvc: {exc}")
        return out

    candidates: list[Any] = []
    for pvc in items:
        ns = pvc.metadata.namespace or ""
        if not namespace and any(ns.startswith(p) for p in _SKIP_NS_PREFIX):
            continue
        phase = (pvc.status.phase if pvc.status else None) or ""
        if phase != "Bound":
            continue
        candidates.append(pvc)

    # Prefer larger requested capacity first (more interesting), then name
    def _sort_key(p: Any) -> tuple:
        req = None
        try:
            req = p.spec.resources.requests.get("storage") if p.spec and p.spec.resources else None
        except Exception:  # noqa: BLE001
            req = None
        return (-(_parse_qty_bytes(str(req)) or 0), p.metadata.namespace or "", p.metadata.name or "")

    candidates.sort(key=_sort_key)
    candidates = candidates[:max_pvcs]

    if not candidates:
        out["warnings"].append("no Bound PVCs to measure")
        return out

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_measure_one, api, pvc): pvc for pvc in candidates}
        for fut in as_completed(futs):
            try:
                row = fut.result()
            except Exception as exc:  # noqa: BLE001
                out["warnings"].append(f"du worker: {exc}")
                continue
            if row:
                results.append(row)

    ok = [r for r in results if r.get("used_percent") is not None]
    ok.sort(key=lambda r: (r.get("used_percent") or 0), reverse=True)
    failed = [r for r in results if r.get("used_percent") is None]
    out["pvc_usage"] = ok + failed
    if failed:
        out["warnings"].append(
            f"{len(failed)}/{len(results)} PVC du incomplete (no mount or no du in image)"
        )
    if ok:
        out["warnings"].append(
            f"per-PVC % from du vs claim request ({len(ok)} measured) — "
            "not kubelet share-wide stats"
        )
    return out

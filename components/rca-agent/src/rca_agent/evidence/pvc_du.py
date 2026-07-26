"""Per-PVC directory usage via `du` in a pod that mounts the claim.

On NFS/shared CSI, kubelet_volume_stats_* reports the whole share — not each PVC.
Measuring `du -sb <mountPath>` against PVC request size gives a usable per-claim %.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import structlog
from kubernetes import client, config
from kubernetes.client.rest import ApiException

log = structlog.get_logger()

_SKIP_NS_PREFIX = ("openshift-", "kube-")


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


def _pvc_request_bytes(pvc: Any) -> int:
    try:
        req = pvc.spec.resources.requests.get("storage") if pvc.spec and pvc.spec.resources else None
    except Exception:  # noqa: BLE001
        req = None
    return _parse_qty_bytes(str(req) if req is not None else None) or 0


def _build_mount_index(
    api: client.CoreV1Api, namespaces: list[str]
) -> dict[tuple[str, str], tuple[str, str, str]]:
    """
    One pods list per namespace → map (ns, pvc_name) -> (pod, container, mount_path).
    Much faster than listing pods once per PVC.
    """
    index: dict[tuple[str, str], tuple[str, str, str]] = {}
    for ns in namespaces:
        try:
            pods = api.list_namespaced_pod(ns).items
        except ApiException as exc:
            log.debug("pvc_du_list_pods_failed", ns=ns, error=str(exc))
            continue
        for pod in pods:
            if (pod.status.phase if pod.status else None) != "Running":
                continue
            if not pod.spec or not pod.spec.volumes:
                continue
            claim_to_vol: dict[str, str] = {}
            for vol in pod.spec.volumes:
                pvc = vol.persistent_volume_claim
                if pvc and pvc.claim_name:
                    claim_to_vol[pvc.claim_name] = vol.name
            if not claim_to_vol:
                continue
            for c in pod.spec.containers or []:
                for vm in c.volume_mounts or []:
                    for claim, vol_name in claim_to_vol.items():
                        if vm.name != vol_name:
                            continue
                        key = (ns, claim)
                        if key in index:
                            continue
                        path = vm.mount_path or ""
                        if vm.sub_path:
                            path = path.rstrip("/") + "/" + vm.sub_path.lstrip("/")
                        if path:
                            index[key] = (pod.metadata.name, c.name, path)
    return index


def _du_bytes(
    *,
    namespace: str,
    pod: str,
    container: str,
    path: str,
    timeout_s: int = 8,
) -> int | None:
    """kubectl exec with explicit in-cluster auth + writable cache under /tmp."""
    kubectl = shutil.which("kubectl")
    if not kubectl:
        log.warning("pvc_du_no_kubectl", ns=namespace, pod=pod)
        return None

    host = os.environ.get("KUBERNETES_SERVICE_HOST")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    if not host or not os.path.isfile(token_path) or not os.path.isfile(ca_path):
        log.warning("pvc_du_no_incluster", ns=namespace, pod=pod, host=bool(host))
        return None

    try:
        with open(token_path, encoding="utf-8") as fh:
            token = fh.read().strip()
    except OSError as exc:
        log.warning("pvc_du_token_read", error=str(exc))
        return None

    cache_dir = "/tmp/kubectl-cache"
    try:
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    except OSError:
        cache_dir = "/tmp"

    base = [
        kubectl,
        f"--server=https://{host}:{port}",
        f"--certificate-authority={ca_path}",
        f"--token={token}",
        f"--cache-dir={cache_dir}",
        "--request-timeout",
        f"{timeout_s}s",
    ]
    env = os.environ.copy()
    env["HOME"] = "/tmp"
    env["KUBECACHEDIR"] = cache_dir

    last_err = ""
    for inner in (
        ["du", "-sb", path],
        ["/bin/sh", "-c", f"du -sb {shlex.quote(path)} 2>/dev/null | cut -f1"],
    ):
        cmd = [
            *base,
            "exec",
            "-n",
            namespace,
            pod,
            "-c",
            container,
            "--",
            *inner,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s + 5,
                check=False,
                env=env,
            )
            text = (proc.stdout or "").strip()
            if proc.returncode == 0 and text:
                first = text.splitlines()[-1].split()[0]
                return int(first)
            last_err = (proc.stderr or proc.stdout or f"rc={proc.returncode}")[:300]
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)

    log.warning(
        "pvc_du_exec_failed",
        ns=namespace,
        pod=pod,
        path=path,
        error=last_err,
        has_kubectl=True,
    )
    return None


def _pick_candidates(
    pvcs: list[Any],
    mounts: dict[tuple[str, str], tuple[str, str, str]],
    *,
    max_pvcs: int,
    namespace: str | None,
) -> list[Any]:
    """Prefer mountable PVCs; cluster-wide: round-robin across namespaces."""
    mountable = [
        p
        for p in pvcs
        if (p.metadata.namespace or "", p.metadata.name or "") in mounts
    ]
    if not mountable:
        return []

    mountable.sort(
        key=lambda p: (
            -_pvc_request_bytes(p),
            p.metadata.namespace or "",
            p.metadata.name or "",
        )
    )

    if namespace:
        return mountable[:max_pvcs]

    by_ns: dict[str, list[Any]] = defaultdict(list)
    for p in mountable:
        by_ns[p.metadata.namespace or ""].append(p)

    # Round-robin so platform + observability + postgres + … all appear
    selected: list[Any] = []
    ns_order = sorted(by_ns.keys(), key=lambda n: (-len(by_ns[n]), n))
    while len(selected) < max_pvcs and by_ns:
        progress = False
        for ns in list(ns_order):
            bucket = by_ns.get(ns) or []
            if not bucket:
                by_ns.pop(ns, None)
                continue
            selected.append(bucket.pop(0))
            progress = True
            if len(selected) >= max_pvcs:
                break
        if not progress:
            break
        ns_order = [n for n in ns_order if by_ns.get(n)]
    return selected


def _measure_one(
    pvc: Any,
    mount: tuple[str, str, str],
) -> dict[str, Any]:
    ns = pvc.metadata.namespace
    name = pvc.metadata.name
    cap = _pvc_request_bytes(pvc) or None
    req = None
    try:
        req = pvc.spec.resources.requests.get("storage") if pvc.spec and pvc.spec.resources else None
    except Exception:  # noqa: BLE001
        req = None
    pod, container, path = mount
    used = _du_bytes(namespace=ns, pod=pod, container=container, path=path)
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
    workers: int = 3,
) -> dict[str, Any]:
    """
    Per-PVC usage = du(mount) / PVC request size.

    Cluster-wide samples across namespaces (not only the largest claims in one ns).
    """
    out: dict[str, Any] = {"pvc_usage": [], "warnings": [], "source": "du"}
    api = _core()
    if not api:
        out["warnings"].append("core api unavailable for pvc du")
        return out

    try:
        if namespace:
            items = list(api.list_namespaced_persistent_volume_claim(namespace).items)
        else:
            items = list(api.list_persistent_volume_claim_for_all_namespaces().items)
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"list pvc: {exc}")
        return out

    bound: list[Any] = []
    for pvc in items:
        ns = pvc.metadata.namespace or ""
        if not namespace and any(ns.startswith(p) for p in _SKIP_NS_PREFIX):
            continue
        phase = (pvc.status.phase if pvc.status else None) or ""
        if phase != "Bound":
            continue
        bound.append(pvc)

    if not bound:
        out["warnings"].append("no Bound PVCs to measure")
        return out

    namespaces = sorted({p.metadata.namespace for p in bound if p.metadata.namespace})
    mounts = _build_mount_index(api, namespaces)
    if not mounts:
        out["warnings"].append("no Running pods mounting Bound PVCs")
        return out

    candidates = _pick_candidates(
        bound, mounts, max_pvcs=max_pvcs, namespace=namespace
    )
    if not candidates:
        out["warnings"].append("no mountable PVCs in selection")
        return out

    out["warnings"].append(
        f"measuring {len(candidates)} PVC(s) across "
        f"{len({p.metadata.namespace for p in candidates})} namespace(s)"
    )

    workers = max(1, min(workers, 3, len(candidates)))
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(
                _measure_one,
                pvc,
                mounts[(pvc.metadata.namespace or "", pvc.metadata.name or "")],
            ): pvc
            for pvc in candidates
        }
        for fut in as_completed(futs):
            try:
                row = fut.result()
            except Exception as exc:  # noqa: BLE001
                out["warnings"].append(f"du worker: {exc}")
                continue
            if row:
                results.append(row)

    ok = [r for r in results if r.get("used_percent") is not None]
    ok.sort(
        key=lambda r: (r.get("used_percent") or 0, r.get("used_bytes") or 0),
        reverse=True,
    )
    failed = [r for r in results if r.get("used_percent") is None]
    out["pvc_usage"] = ok + failed
    if failed:
        out["warnings"].append(
            f"{len(failed)}/{len(results)} PVC du incomplete (exec/du missing in image)"
        )
    if ok:
        out["warnings"].append(
            f"per-PVC % from du vs claim request ({len(ok)} measured) — "
            "not kubelet share-wide stats"
        )
    return out

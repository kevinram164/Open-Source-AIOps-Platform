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


def _redact_secrets(text: str) -> str:
    """Never surface SA JWT / full kubectl argv in logs or API warnings."""
    if not text:
        return text
    out = re.sub(r"--token=\S+", "--token=[redacted]", text)
    out = re.sub(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", "[jwt]", out)
    if "Command '" in out or "Command [" in out:
        # TimeoutExpired embeds full argv — keep only a short reason
        if "timed out" in out.lower() or "TimeoutExpired" in out:
            return "kubectl exec timed out"
        return "kubectl exec failed"
    return out[:300]


def _parse_du_stdout(text: str, *, unit: str) -> int | None:
    """Parse `du` first field; unit is 'b' (bytes) or 'k' (KiB)."""
    text = (text or "").strip()
    if not text:
        return None
    first = text.splitlines()[-1].split()[0]
    try:
        n = int(first)
    except ValueError:
        return None
    if unit == "k":
        return n * 1024
    return n


def _parse_df_used(text: str, *, block_size: int) -> int | None:
    """Parse df Used column; block_size is 1 (df -B1) or 1024 (df -Pk)."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    parts = lines[-1].split()
    if len(parts) < 3:
        return None
    try:
        used_blocks = int(parts[2])
    except ValueError:
        return None
    return used_blocks * block_size


def _kubectl_exec(
    *,
    namespace: str,
    pod: str,
    container: str,
    inner: list[str],
    timeout_s: int,
) -> tuple[int, str, str]:
    """Returns (returncode, stdout, err_short) — never embeds SA token."""
    kubectl = shutil.which("kubectl")
    if not kubectl:
        return 1, "", "kubectl not found"

    host = os.environ.get("KUBERNETES_SERVICE_HOST")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    if not host or not os.path.isfile(token_path) or not os.path.isfile(ca_path):
        return 1, "", "in-cluster auth unavailable"

    try:
        with open(token_path, encoding="utf-8") as fh:
            token = fh.read().strip()
    except OSError as exc:
        return 1, "", f"token read: {exc}"

    cache_dir = "/tmp/kubectl-cache"
    try:
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    except OSError:
        cache_dir = "/tmp"

    cmd = [
        kubectl,
        f"--server=https://{host}:{port}",
        f"--certificate-authority={ca_path}",
        f"--token={token}",
        f"--cache-dir={cache_dir}",
        "--request-timeout",
        f"{timeout_s}s",
        "exec",
        "-n",
        namespace,
        pod,
        "-c",
        container,
        "--",
        *inner,
    ]
    env = os.environ.copy()
    env["HOME"] = "/tmp"
    env["KUBECACHEDIR"] = cache_dir
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s + 5,
            check=False,
            env=env,
        )
        err = _redact_secrets((proc.stderr or "")[:300])
        return proc.returncode, proc.stdout or "", err or f"rc={proc.returncode}"
    except subprocess.TimeoutExpired:
        return 1, "", f"kubectl exec timed out after {timeout_s}s"
    except Exception as exc:  # noqa: BLE001
        return 1, "", _redact_secrets(str(exc))


def _du_bytes(
    *,
    namespace: str,
    pod: str,
    container: str,
    path: str,
    timeout_s: int = 22,
) -> tuple[int | None, str]:
    """
    Return (used_bytes, method). Prefer du -sk; on timeout/fail use df on mount.
    Note: df on shared NFS reflects the whole share — caller must sanity-check vs claim.
    """
    attempts: list[tuple[list[str], str]] = [
        (["du", "-sk", path], "k"),
        (["/usr/bin/du", "-sk", path], "k"),
        (["du", "-sb", path], "b"),
        (
            ["/bin/sh", "-c", f"du -sk {shlex.quote(path)} 2>/dev/null | cut -f1"],
            "k",
        ),
    ]

    last_err = ""
    for inner, unit in attempts:
        rc, stdout, err = _kubectl_exec(
            namespace=namespace,
            pod=pod,
            container=container,
            inner=inner,
            timeout_s=timeout_s,
        )
        parsed = _parse_du_stdout(stdout, unit=unit)
        if rc == 0 and parsed is not None:
            return parsed, "du"
        last_err = err
        if "timed out" in err:
            break

    for inner, block_size in ((["df", "-B1", path], 1), (["df", "-Pk", path], 1024)):
        rc, stdout, err = _kubectl_exec(
            namespace=namespace,
            pod=pod,
            container=container,
            inner=inner,
            timeout_s=8,
        )
        used = _parse_df_used(stdout, block_size=block_size)
        if rc == 0 and used is not None:
            return used, "df"
        last_err = err or last_err

    log.warning(
        "pvc_du_exec_failed",
        ns=namespace,
        pod=pod,
        path=path,
        error=last_err,
        has_kubectl=True,
    )
    return None, "du"


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
    used, method = _du_bytes(namespace=ns, pod=pod, container=container, path=path)
    if used is None:
        return {
            "namespace": ns,
            "persistentvolumeclaim": name,
            "method": method,
            "error": "du_failed",
            "pod": pod,
            "mount_path": path,
            "capacity_bytes": cap,
            "capacity_human": _fmt_bytes(cap) if cap else None,
            "request": str(req) if req else None,
        }

    # used ≫ claim → shared NFS / df share / unit bug — do not report as "hot PVC"
    if cap and cap > 0 and used > cap * 2:
        return {
            "namespace": ns,
            "persistentvolumeclaim": name,
            "method": method,
            "error": "used_exceeds_claim",
            "warning": (
                f"measured { _fmt_bytes(used) } > 2× claim { _fmt_bytes(cap) } "
                f"(shared FS or bad parse via {method}) — % skipped"
            ),
            "pod": pod,
            "mount_path": path,
            "used_bytes": used,
            "used_human": _fmt_bytes(used),
            "capacity_bytes": cap,
            "capacity_human": _fmt_bytes(cap),
            "request": str(req) if req else None,
            "used_percent": None,
        }

    pct = round(100.0 * used / cap, 1) if cap and cap > 0 else None
    return {
        "namespace": ns,
        "persistentvolumeclaim": name,
        "method": method,
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
                if row.get("warning"):
                    out["warnings"].append(
                        f"{row.get('namespace')}/{row.get('persistentvolumeclaim')}: "
                        f"{row['warning']}"
                    )

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

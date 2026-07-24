"""GitOps scale via GitHub Pull Request."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import httpx
import yaml

from remediation_controller.config import settings

LOG = logging.getLogger(__name__)


def _load_targets() -> dict:
    path = Path(settings.gitops_targets_path)
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text()) or {}
    return dict(raw.get("targets") or {})


def _set_nested(data: dict, dotted_key: str, value: int) -> None:
    parts = dotted_key.split(".")
    cur = data
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def resolve_target(namespace: str, deployment: str) -> dict:
    key = f"{namespace}/{deployment}"
    targets = _load_targets()
    if key not in targets:
        raise ValueError(f"no gitops target mapping for {key}")
    return targets[key]


def open_scale_pr(*, namespace: str, deployment: str, replicas: int, reason: str | None) -> str:
    if not settings.github_token:
        raise RuntimeError("GITHUB_TOKEN not configured")

    mapping = resolve_target(namespace, deployment)
    owner = mapping["owner"]
    repo = mapping["repo"]
    path = mapping["path"]
    replica_key = mapping["replicaKey"]
    base = mapping.get("baseBranch", "main")
    branch = f"aiops/scale-{namespace}-{deployment}-{replicas}"

    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    api = settings.github_api_url.rstrip("/")

    with httpx.Client(timeout=60.0, headers=headers) as client:
        # base commit sha
        ref = client.get(f"{api}/repos/{owner}/{repo}/git/ref/heads/{base}")
        ref.raise_for_status()
        base_sha = ref.json()["object"]["sha"]

        # file content
        file_resp = client.get(
            f"{api}/repos/{owner}/{repo}/contents/{path}",
            params={"ref": base},
        )
        file_resp.raise_for_status()
        file_json = file_resp.json()
        content = base64.b64decode(file_json["content"]).decode("utf-8")
        data = yaml.safe_load(content) or {}
        _set_nested(data, replica_key, replicas)
        new_content = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)

        # create / update branch
        ref_create = client.post(
            f"{api}/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        if ref_create.status_code == 422:
            # branch exists — move tip to base then overwrite file
            client.patch(
                f"{api}/repos/{owner}/{repo}/git/refs/heads/{branch}",
                json={"sha": base_sha, "force": True},
            ).raise_for_status()
        else:
            ref_create.raise_for_status()

        put = client.put(
            f"{api}/repos/{owner}/{repo}/contents/{path}",
            json={
                "message": f"aiops: scale {deployment} to {replicas} in {namespace}",
                "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
                "branch": branch,
                "sha": file_json["sha"],
            },
        )
        # if branch already had different sha for file, refetch
        if put.status_code == 409:
            file2 = client.get(
                f"{api}/repos/{owner}/{repo}/contents/{path}",
                params={"ref": branch},
            )
            file2.raise_for_status()
            put = client.put(
                f"{api}/repos/{owner}/{repo}/contents/{path}",
                json={
                    "message": f"aiops: scale {deployment} to {replicas} in {namespace}",
                    "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
                    "branch": branch,
                    "sha": file2.json()["sha"],
                },
            )
        put.raise_for_status()

        title = f"[AIOps] Scale {namespace}/{deployment} → {replicas}"
        body = (
            f"Automated remediation (Policy Mode B).\n\n"
            f"- Namespace: `{namespace}`\n"
            f"- Deployment: `{deployment}`\n"
            f"- Replicas: `{replicas}`\n"
            f"- Reason: {reason or 'n/a'}\n\n"
            f"Merge to let Argo CD sync (durable scale)."
        )
        pr = client.post(
            f"{api}/repos/{owner}/{repo}/pulls",
            json={"title": title, "head": branch, "base": base, "body": body},
        )
        if pr.status_code == 422:
            # PR may already exist
            existing = client.get(
                f"{api}/repos/{owner}/{repo}/pulls",
                params={"head": f"{owner}:{branch}", "state": "open"},
            )
            existing.raise_for_status()
            items = existing.json()
            if items:
                return items[0]["html_url"]
            pr.raise_for_status()
        pr.raise_for_status()
        return pr.json()["html_url"]

"""Kubernetes / GitOps / Ansible remediation actions."""

from __future__ import annotations

from datetime import UTC, datetime

from kubernetes import client, config

from remediation_controller import gitops
from remediation_controller.ansible_job import run_node_diagnostics


def _apps() -> client.AppsV1Api:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.AppsV1Api()


def restart_deployment(namespace: str, name: str) -> str:
    api = _apps()
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "aiops.platform/restartedAt": now,
                        "kubectl.kubernetes.io/restartedAt": now,
                    }
                }
            }
        }
    }
    api.patch_namespaced_deployment(name=name, namespace=namespace, body=body)
    return f"restarted deployment/{name} in {namespace} at {now}"


def scale_deployment(namespace: str, name: str, replicas: int) -> str:
    """Live scale — ephemeral under Argo selfHeal; prefer gitops-scale for durable change."""
    api = _apps()
    api.patch_namespaced_deployment_scale(
        name=name,
        namespace=namespace,
        body={"spec": {"replicas": replicas}},
    )
    return (
        f"scaled deployment/{name} in {namespace} to replicas={replicas} "
        "(ephemeral if ArgoCD selfHeal is on — use gitops-scale for durable)"
    )


def gitops_scale(namespace: str, name: str, replicas: int, reason: str | None) -> str:
    url = gitops.open_scale_pr(
        namespace=namespace,
        deployment=name,
        replicas=replicas,
        reason=reason,
    )
    return f"opened GitOps PR for durable scale: {url}"


def ansible_runbook(
    *,
    playbook: str,
    namespace: str,
    target: str,
    parameters: dict,
    remediation_id: str,
) -> str:
    if playbook != "node-diagnostics":
        raise ValueError(f"unsupported playbook: {playbook}")
    node = parameters.get("node") or (target if target != "cluster" else None)
    return run_node_diagnostics(node=node, remediation_id=remediation_id)

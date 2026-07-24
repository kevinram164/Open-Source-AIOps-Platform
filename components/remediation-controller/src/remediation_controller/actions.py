"""Kubernetes remediation actions."""

from __future__ import annotations

from datetime import UTC, datetime

from kubernetes import client, config


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
    api = _apps()
    api.patch_namespaced_deployment_scale(
        name=name,
        namespace=namespace,
        body={"spec": {"replicas": replicas}},
    )
    return f"scaled deployment/{name} in {namespace} to replicas={replicas}"

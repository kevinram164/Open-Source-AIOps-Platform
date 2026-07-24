"""Create and wait for diagnostic runbook Jobs (Ansible Type 3)."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from kubernetes import client, config

from remediation_controller.config import settings


def _batch() -> client.BatchV1Api:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.BatchV1Api()


def _core() -> client.CoreV1Api:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


def run_node_diagnostics(*, node: str | None, remediation_id: str) -> str:
    """Spawn a Job that collects node/pod diagnostics via kubectl (lab runbook)."""
    batch = _batch()
    core = _core()
    ns = settings.ansible_job_namespace
    image = settings.ansible_job_image or "harbor-platform.apps.ocp01.npd.co/aiops/remediation-controller:0.5.0"
    job_name = f"aiops-runbook-{remediation_id[:8]}".lower().replace("_", "-")
    node_arg = node or ""

    script = r"""
set -euo pipefail
echo "=== AIOps node-diagnostics runbook ==="
echo "node=${NODE_NAME:-all}"
echo "time=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo
echo "--- nodes ---"
kubectl get nodes -o wide || true
echo
if [ -n "${NODE_NAME:-}" ]; then
  echo "--- describe node ${NODE_NAME} ---"
  kubectl describe node "${NODE_NAME}" || true
  echo
  echo "--- pods on node ---"
  kubectl get pods -A --field-selector spec.nodeName="${NODE_NAME}" -o wide || true
else
  echo "--- top nodes (best effort) ---"
  kubectl top nodes || true
fi
echo
echo "--- recent warning events ---"
kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp | tail -n 40 || true
echo
echo "=== runbook complete ==="
"""

    body = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=ns,
            labels={
                "app.kubernetes.io/part-of": "open-aiops-platform",
                "aiops.platform/runbook": "node-diagnostics",
                "aiops.platform/remediation-id": remediation_id[:63],
            },
        ),
        spec=client.V1JobSpec(
            ttl_seconds_after_finished=settings.ansible_job_ttl_seconds,
            backoff_limit=0,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    labels={
                        "app.kubernetes.io/name": "aiops-runbook",
                        "aiops.platform/runbook": "node-diagnostics",
                    }
                ),
                spec=client.V1PodSpec(
                    service_account_name=settings.ansible_job_service_account,
                    restart_policy="Never",
                    containers=[
                        client.V1Container(
                            name="runbook",
                            image=image,
                            image_pull_policy="IfNotPresent",
                            command=["/bin/sh", "-c", script],
                            env=[
                                client.V1EnvVar(name="NODE_NAME", value=node_arg),
                            ],
                            security_context=client.V1SecurityContext(
                                allow_privilege_escalation=False,
                                run_as_non_root=True,
                                read_only_root_filesystem=True,
                                capabilities=client.V1Capabilities(drop=["ALL"]),
                            ),
                        )
                    ],
                ),
            ),
        ),
    )

    # Prefer bitnami/kubectl for the Job if remediation image has no kubectl —
    # override container to use kubectl image with same script.
    body.spec.template.spec.containers[0].image = "bitnami/kubectl:1.30"
    body.spec.template.spec.containers[0].command = ["/bin/bash", "-c", script]
    body.spec.template.spec.containers[0].security_context.run_as_non_root = True

    try:
        batch.delete_namespaced_job(
            name=job_name,
            namespace=ns,
            body=client.V1DeleteOptions(propagation_policy="Background"),
        )
        time.sleep(1)
    except client.exceptions.ApiException as exc:
        if exc.status != 404:
            raise

    batch.create_namespaced_job(namespace=ns, body=body)

    # Wait up to ~3 minutes
    deadline = time.time() + 180
    while time.time() < deadline:
        job = batch.read_namespaced_job(name=job_name, namespace=ns)
        succeeded = (job.status.succeeded or 0) > 0
        failed = (job.status.failed or 0) > 0
        if succeeded or failed:
            pods = core.list_namespaced_pod(
                namespace=ns,
                label_selector=f"job-name={job_name}",
            )
            logs = ""
            if pods.items:
                pname = pods.items[0].metadata.name
                try:
                    logs = core.read_namespaced_pod_log(name=pname, namespace=ns, tail_lines=80)
                except client.exceptions.ApiException:
                    logs = "(no logs)"
            if failed:
                raise RuntimeError(f"runbook Job {job_name} failed\n{logs}")
            return f"runbook Job {job_name} completed at {datetime.now(UTC).isoformat()}\n{logs}"
        time.sleep(3)

    raise TimeoutError(f"runbook Job {job_name} timed out")

"""Sync AlertmanagerConfig into every non-denied namespace (Policy Mode B)."""

from __future__ import annotations

import logging
import os
import sys

from kubernetes import client, config

from remediation_controller.policy import load_policy

LOG = logging.getLogger("amc-sync")

AMC_NAME = "aiops-webhook"
AMC_GROUP = "monitoring.coreos.com"
AMC_VERSION = "v1alpha1"
AMC_PLURAL = "alertmanagerconfigs"


def _clients() -> tuple[client.CoreV1Api, client.CustomObjectsApi]:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api(), client.CustomObjectsApi()


def _desired_body(webhook_url: str) -> dict:
    return {
        "apiVersion": f"{AMC_GROUP}/{AMC_VERSION}",
        "kind": "AlertmanagerConfig",
        "metadata": {
            "name": AMC_NAME,
            "labels": {
                "app.kubernetes.io/part-of": "open-aiops-platform",
                "alertmanagerConfig": "aiops",
                "aiops.platform/managed-by": "amc-sync",
            },
        },
        "spec": {
            "route": {
                "receiver": "aiops-webhook",
                "groupBy": ["namespace", "alertname"],
                "groupWait": "30s",
                "groupInterval": "5m",
                "repeatInterval": "4h",
            },
            "receivers": [
                {
                    "name": "aiops-webhook",
                    "webhookConfigs": [
                        {
                            "url": webhook_url,
                            "sendResolved": True,
                        }
                    ],
                }
            ],
        },
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    policy = load_policy()
    webhook = os.environ.get(
        "AMC_WEBHOOK_URL",
        "http://incident-api.aiops-core.svc.cluster.local:8080/api/v1/alerts",
    )
    core, custom = _clients()

    created = updated = skipped = errors = 0
    for ns in core.list_namespace().items:
        name = ns.metadata.name
        if not policy.allows_namespace(name):
            skipped += 1
            continue
        body = _desired_body(webhook)
        try:
            existing = None
            try:
                existing = custom.get_namespaced_custom_object(
                    AMC_GROUP, AMC_VERSION, name, AMC_PLURAL, AMC_NAME
                )
            except client.exceptions.ApiException as exc:
                if exc.status != 404:
                    raise
            if existing is None:
                custom.create_namespaced_custom_object(
                    AMC_GROUP, AMC_VERSION, name, AMC_PLURAL, body
                )
                LOG.info("created AlertmanagerConfig/%s in %s", AMC_NAME, name)
                created += 1
            else:
                body["metadata"]["resourceVersion"] = existing["metadata"]["resourceVersion"]
                custom.replace_namespaced_custom_object(
                    AMC_GROUP, AMC_VERSION, name, AMC_PLURAL, AMC_NAME, body
                )
                LOG.info("updated AlertmanagerConfig/%s in %s", AMC_NAME, name)
                updated += 1
        except Exception as exc:  # noqa: BLE001
            LOG.error("failed ns=%s: %s", name, exc)
            errors += 1

    LOG.info(
        "amc-sync done mode=%s created=%s updated=%s skipped=%s errors=%s",
        policy.policy_mode,
        created,
        updated,
        skipped,
        errors,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

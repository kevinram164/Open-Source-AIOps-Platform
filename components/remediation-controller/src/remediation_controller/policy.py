"""Load and evaluate Mode B policy (observe ≠ remediate)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from remediation_controller.config import settings


def _denied(namespace: str, prefixes: list[str], names: list[str]) -> bool:
    if namespace in names:
        return True
    return any(namespace.startswith(p) for p in prefixes)


@dataclass
class Policy:
    policy_mode: str = "B"
    require_approval: bool = True
    # Alert ingest / AMC sync — keep narrow (system only by default)
    observe_deny_namespace_prefixes: list[str] = field(default_factory=list)
    observe_deny_namespaces: list[str] = field(default_factory=list)
    # Write remediation — protect platform/infra (vault, argocd, …)
    remediation_deny_namespace_prefixes: list[str] = field(default_factory=list)
    remediation_deny_namespaces: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    max_scale_replicas: int = 10

    def allows_observe_namespace(self, namespace: str) -> bool:
        return not _denied(
            namespace,
            self.observe_deny_namespace_prefixes,
            self.observe_deny_namespaces,
        )

    def allows_remediation_namespace(self, namespace: str) -> bool:
        return not _denied(
            namespace,
            self.remediation_deny_namespace_prefixes,
            self.remediation_deny_namespaces,
        )

    # Back-compat alias used by older call sites
    def allows_namespace(self, namespace: str) -> bool:
        return self.allows_remediation_namespace(namespace)

    def allows_action(self, action: str) -> bool:
        return action in self.allowed_actions


def load_policy(path: str | None = None) -> Policy:
    p = Path(path or settings.policy_path)
    if not p.exists():
        return Policy(
            observe_deny_namespace_prefixes=["openshift-", "kube-"],
            observe_deny_namespaces=[],
            remediation_deny_namespace_prefixes=["openshift-", "kube-"],
            remediation_deny_namespaces=["default", "vault", "argocd"],
            allowed_actions=[
                "restart-deployment",
                "scale-deployment",
                "gitops-scale",
                "ansible-runbook",
            ],
            max_scale_replicas=settings.max_scale_replicas_default,
        )
    raw = yaml.safe_load(p.read_text()) or {}

    # Prefer explicit observe*/remediation*; fall back to legacy deny* for remediation only
    legacy_prefixes = list(raw.get("denyNamespacePrefixes") or ["openshift-", "kube-"])
    legacy_names = list(raw.get("denyNamespaces") or [])

    observe_prefixes = list(
        raw.get("observeDenyNamespacePrefixes")
        or ["openshift-", "kube-"]
    )
    observe_names = list(raw.get("observeDenyNamespaces") or [])

    rem_prefixes = list(raw.get("remediationDenyNamespacePrefixes") or legacy_prefixes)
    rem_names = list(raw.get("remediationDenyNamespaces") or legacy_names)

    return Policy(
        policy_mode=str(raw.get("policyMode", "B")),
        require_approval=bool(raw.get("requireApproval", True)),
        observe_deny_namespace_prefixes=observe_prefixes,
        observe_deny_namespaces=observe_names,
        remediation_deny_namespace_prefixes=rem_prefixes,
        remediation_deny_namespaces=rem_names,
        allowed_actions=list(raw.get("allowedActions") or []),
        max_scale_replicas=int(raw.get("maxScaleReplicas") or settings.max_scale_replicas_default),
    )

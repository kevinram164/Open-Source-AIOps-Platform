"""Load and evaluate Mode B remediation policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from remediation_controller.config import settings


@dataclass
class Policy:
    policy_mode: str = "B"
    require_approval: bool = True
    deny_namespace_prefixes: list[str] = field(default_factory=list)
    deny_namespaces: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    max_scale_replicas: int = 10

    def allows_namespace(self, namespace: str) -> bool:
        if namespace in self.deny_namespaces:
            return False
        for prefix in self.deny_namespace_prefixes:
            if namespace.startswith(prefix):
                return False
        return True

    def allows_action(self, action: str) -> bool:
        return action in self.allowed_actions


def load_policy(path: str | None = None) -> Policy:
    p = Path(path or settings.policy_path)
    if not p.exists():
        return Policy(
            deny_namespace_prefixes=["openshift-", "kube-"],
            deny_namespaces=["default", "vault", "argocd"],
            allowed_actions=["restart-deployment", "scale-deployment"],
            max_scale_replicas=settings.max_scale_replicas_default,
        )
    raw = yaml.safe_load(p.read_text()) or {}
    return Policy(
        policy_mode=str(raw.get("policyMode", "B")),
        require_approval=bool(raw.get("requireApproval", True)),
        deny_namespace_prefixes=list(raw.get("denyNamespacePrefixes") or []),
        deny_namespaces=list(raw.get("denyNamespaces") or []),
        allowed_actions=list(raw.get("allowedActions") or []),
        max_scale_replicas=int(raw.get("maxScaleReplicas") or settings.max_scale_replicas_default),
    )

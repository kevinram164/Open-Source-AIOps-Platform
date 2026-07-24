# Automation — Phase 4

## Ansible runbooks

Playbooks live under `ansible/`. Lab execution is via remediation action `ansible-runbook`
(creates a Job in `aiops-automation` using `bitnami/kubectl` — no AWX required).

| Playbook | Parameters | Effect |
|----------|------------|--------|
| `node-diagnostics` | `node` (optional) | kubectl node/events dump |

## GitOps

Durable scale: remediation action `gitops-scale` opens a GitHub PR using map in
ConfigMap `aiops-gitops-targets`.

## Argo Workflows

Optional later — Jobs cover lab needs.

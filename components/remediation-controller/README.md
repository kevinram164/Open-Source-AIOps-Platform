# Remediation Controller — Phase 4 (complete)

Policy Mode B: approve then execute.

| Action | Purpose |
|--------|---------|
| `restart-deployment` | Live rollout restart |
| `scale-deployment` | Live scale (ephemeral under Argo) |
| `gitops-scale` | GitHub PR for durable replicas |
| `ansible-runbook` | Job-based node diagnostics |

State persisted in Postgres (`remediations`, `audit_log`).

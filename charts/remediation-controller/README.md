# Remediation Controller Helm chart (Phase 4)

Deploys:

- Deployment + Service + Route (`remediation-controller`)
- CronJob AMC sync (`*-amc-sync`) — Policy Mode B auto-onboard AlertmanagerConfig

Policy ConfigMap `aiops-remediation-policy` must exist in `aiops-automation` (bootstrap).

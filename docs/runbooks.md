# Runbooks — Remediation (Phase 4 complete, Policy Mode B)

Lab routes use self-signed certs → always `curl -skS`.

## Actions

| Action | Durable? | Notes |
|--------|----------|-------|
| `restart-deployment` | Yes (ops) | Rollout restart |
| `scale-deployment` | **No** (Argo selfHeal) | Emergency only |
| `gitops-scale` | **Yes** | Opens GitHub PR → merge → Argo sync |
| `ansible-runbook` | N/A | Job `node-diagnostics` |

## 1) Restart

```bash
BASE=https://remediation-controller-aiops-automation.apps.ocp01.npd.co
curl -skS -X POST "$BASE/api/v1/remediations" -H 'Content-Type: application/json' -d '{
  "action": "restart-deployment",
  "namespace": "npd-movie",
  "target": "movie-web",
  "reason": "smoke restart"
}' | jq
# approve → execute with returned id
curl -skS -X POST "$BASE/api/v1/remediations/REM_ID/approve?approved_by=kevin" | jq
curl -skS -X POST "$BASE/api/v1/remediations/REM_ID/execute" | jq
```

## 2) Durable scale (GitOps PR)

```bash
curl -skS -X POST "$BASE/api/v1/remediations" -H 'Content-Type: application/json' -d '{
  "action": "gitops-scale",
  "namespace": "npd-movie",
  "target": "movie-web",
  "parameters": {"replicas": 2},
  "reason": "durable scale via PR"
}' | jq
curl -skS -X POST "$BASE/api/v1/remediations/REM_ID/approve?approved_by=kevin" | jq
curl -skS -X POST "$BASE/api/v1/remediations/REM_ID/execute" | jq
# result contains PR URL — merge PR, Argo syncs replicas
```

Targets map: ConfigMap `aiops-gitops-targets` (`npd-movie/movie-web`, `npd-banking/frontend`, …).

## 3) Ansible runbook (node diagnostics)

```bash
curl -skS -X POST "$BASE/api/v1/remediations" -H 'Content-Type: application/json' -d '{
  "action": "ansible-runbook",
  "namespace": "aiops-automation",
  "target": "cluster",
  "parameters": {"playbook": "node-diagnostics"},
  "reason": "cluster health dump"
}' | jq
# approve → execute; result includes Job logs
```

## Policy / list

```bash
curl -skS "$BASE/api/v1/policy" | jq
curl -skS "$BASE/api/v1/remediations" | jq
```

Remediations + `audit_log` persist in shared Postgres DB `aiops`.

## 4) NBA — analyze → pending remediation

```bash
INC=https://incident-api-aiops-core.apps.ocp01.npd.co
curl -skS -X POST "$INC/api/v1/incidents/UUID/analyze" | jq '{status, nba}'
# Approve NBA draft ids under .nba.remediations[].id  (see docs/nba.md)
```

## 5) Grafana (Phase 5)

- https://grafana-aiops-observability.apps.ocp01.npd.co  
- Dashboard **AIOps / AIOps Overview**  
- Vault: `secret/aiops/grafana` (`admin-user`, `admin-password`)

# Next Best Action (NBA)

After `POST /api/v1/incidents/{id}/analyze`:

1. RCA Agent returns JSON (`suggested_actions` + free-text recommendations)
2. Incident API persists `rca_results`
3. NBA mapper creates **pending** remediations via Remediation Controller
4. On-call **approve → execute** (Phase 4) — no auto-run

## Heuristic (if no structured `suggested_actions`)

| Evidence / text | Draft action |
|-----------------|--------------|
| CrashLoop / ImagePull / OOM / restart | `restart-deployment` |
| scale / replicas | `gitops-scale` |
| node / NotReady / pressure | `ansible-runbook` (`node-diagnostics`) |

## Example

```bash
# Analyze → look at nba.remediations
curl -skS -X POST https://incident-api-aiops-core.apps.ocp01.npd.co/api/v1/incidents/UUID/analyze | jq .nba

# Approve draft
curl -skS -X POST "https://remediation-controller-aiops-automation.apps.ocp01.npd.co/api/v1/remediations/REM_ID/approve?approved_by=kevin"
curl -skS -X POST ".../REM_ID/execute"
```

Grafana: pending NBA count on **AIOps Overview**.

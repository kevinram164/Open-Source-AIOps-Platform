# Grafana Integration (Phase 5)

Dashboard **AIOps Overview**: incidents, RCA+NBA, remediations.

- Chart: `charts/grafana`
- Argo app: `grafana` (ns `aiops-observability`)
- Route: `https://grafana-aiops-observability.apps.ocp01.npd.co`
- Datasources: Thanos Querier + Postgres DB `aiops`

## Seed Vault

```bash
vault kv put secret/aiops/grafana \
  admin-user='admin' \
  admin-password='ChangeMe-Aiops-Grafana-2026'
```

ESO syncs `grafana-admin` + `grafana-postgres` into `aiops-observability`.

## OpenShift note

Chart dùng **restricted-v2** (không `fsGroup: 472`). Data Grafana = emptyDir (lab OK; dashboard provision từ ConfigMap).

Không cần `anyuid` SCC.

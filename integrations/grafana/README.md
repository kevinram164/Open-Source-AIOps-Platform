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

Nếu pod Grafana bị SCC/`fsGroup` chặn PVC:

```bash
oc adm policy add-scc-to-user anyuid -z grafana -n aiops-observability
```

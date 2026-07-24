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

## Troubleshooting "No data"

Log Grafana: `lookup postgres-ha-...: Try again` → **NetworkPolicy chặn DNS**.
Sync bootstrap / apply `bootstrap/network-policies/aiops-observability-netpol.yaml`
(egress tới `openshift-dns` ports 53 + 5353).

Postgres là StatefulSet pod `postgres-ha-postgresql-primary-0` (không phải Deployment):

```bash
oc exec -n postgres postgres-ha-postgresql-primary-0 -c postgresql -- \
  env PGPASSWORD="$(oc get secret aiops-db -n postgres -o jsonpath='{.data.password}' | base64 -d)" \
  psql -U aiops -d aiops -c 'SELECT COUNT(*) FROM incidents;'
```

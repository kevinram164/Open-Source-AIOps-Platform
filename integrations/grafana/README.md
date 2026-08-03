# Grafana Integration (Phase 5)

Dashboard **AIOps Overview**: incidents, RCA+NBA, remediations.

- Chart: `charts/grafana`
- Argo app: `grafana` (ns `aiops-observability`)
- Route: `https://grafana-aiops-observability.apps.ocp01.npd.co`
- Datasources: Thanos Querier + Postgres DB `aiops`

## NPD dashboards (folder **NPD**)

| Dashboard | Scope |
|-----------|--------|
| NPD Banking | `npd-banking` pods/CPU/mem |
| NPD Shop | `npd-shop` |
| NPD Infra | postgres/redis/kong/kafka/rabbit + Kafka lag |
| NPD OCP Nodes | CPU/mem/disk all nodes |

JSON: `charts/grafana/dashboards/npd-*.json`.  
Scrape + Telegram alerts: `banking-demo/phase9-gitops-platform/monitoring/DEPLOY.md`.  
Grafana SA: `cluster-monitoring-view` + Secret `grafana-thanos-token`.

## Seed Vault

```bash
vault kv put secret/aiops/grafana \
  admin-user='admin' \
  admin-password='ChangeMe-Aiops-Grafana-2026'
```

ESO syncs `grafana-admin` + `grafana-postgres` into `aiops-observability`.

## Troubleshooting "No data"

DB có data (`SELECT COUNT(*) FROM incidents` = 1) nhưng Grafana `getent hosts` fail
→ NetPol từng chặn DNS. Lab: observability **chỉ deny ingress**, không restrict egress
(giống `aiops-core`).

```bash
oc apply -f bootstrap/network-policies/aiops-observability-netpol.yaml
oc exec -n aiops-observability deploy/grafana -- \
  getent hosts postgres-ha-postgresql-primary.postgres.svc.cluster.local
```

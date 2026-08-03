# Grafana Integration (Phase 5)

Dashboard **AIOps Overview**: incidents, RCA+NBA, remediations.

- Chart: `charts/grafana`
- Argo app: `grafana` (ns `aiops-observability`)
- Route: `https://grafana-aiops-observability.apps.ocp01.npd.co`
- Datasources: Thanos Querier + Postgres DB `aiops`

## NPD dashboards (folder **NPD**)

Port từ `banking-demo/phase3-monitoring-keda/helm-monitoring/` (+ Nodes/Infra overview):

| Dashboard | Scope |
|-----------|--------|
| NPD Banking Services | HTTP RPS/p95/errors/transfer (Phase 8) |
| NPD Shop Services | HTTP shop |
| NPD Kong Gateway | Kong metrics |
| NPD RabbitMQ | Rabbit metrics |
| NPD Infra | postgres/redis/kong/kafka/rabbit + lag |
| NPD OCP Nodes | CPU/mem/disk all nodes |

Script: `banking-demo/phase9-gitops-platform/monitoring/scripts/port_phase3_dashboards.py`  
Scrape + Telegram: `banking-demo/phase9-gitops-platform/monitoring/DEPLOY.md`.  
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

# Secret / Vault — reuse shared platform (KHÔNG deploy Postgres/Redis/Harbor mới).

## OpenAI API Key (Phase 3; tạo sẵn được)

```bash
oc create secret generic openai-api-key \
  -n aiops-core \
  --from-literal=OPENAI_API_KEY='sk-...' \
  --dry-run=client -o yaml | oc apply -f -
```

## Postgres — DB `aiops` trên **postgres-ha** (ns `postgres`)

Giống movie/banking: chỉ tạo role+DB mới, không đụng secret `postgres-ha-postgresql`.

```bash
PG_PASS='ChangeMe-Aiops-Pg-2026'

# 1) Password cho Job db-init (ns postgres)
oc create secret generic aiops-db \
  -n postgres \
  --from-literal=password="${PG_PASS}" \
  --dry-run=client -o yaml | oc apply -f -

# 2) Secret app (ns aiops-core) — Incident API đọc DATABASE_URL
oc create secret generic postgresql-credentials \
  -n aiops-core \
  --from-literal=DATABASE_URL="postgresql+asyncpg://aiops:${PG_PASS}@postgres-ha-postgresql-primary.postgres.svc.cluster.local:5432/aiops" \
  --dry-run=client -o yaml | oc apply -f -
```

Vault (khuyến nghị, giống cinehome):

```sh
vault kv put secret/aiops/db password='ChangeMe-Aiops-Pg-2026'
vault kv put secret/aiops/app \
  DATABASE_URL='postgresql+asyncpg://aiops:ChangeMe-Aiops-Pg-2026@postgres-ha-postgresql-primary.postgres.svc.cluster.local:5432/aiops'
# Grafana UI (Phase 5)
vault kv put secret/aiops/grafana \
  admin-user='admin' \
  admin-password='ChangeMe-Aiops-Grafana-2026'
# (optional) OPENAI_API_KEY trong secret/aiops/openai
```

Rồi ESO → Secret `aiops-db` (postgres) + `postgresql-credentials` (aiops-core).

## Harbor — project `aiops` (đã có Harbor platform)

- Project Harbor: `aiops`
- Robot CI: seed Vault `secret/aiops/harbor` (`username`, `password`)
- Pull secret ns `aiops-core`: copy/ESO từ `secret/aiops/harbor-pull` → `harbor-pull-secret`
- Jenkins: `vaultHarborPath: 'aiops/harbor'`, extend policy `jenkins-kaniko`

## Không tạo lại

| Đã có trên lab | Dùng cho AIOps |
|----------------|----------------|
| postgres-ha | DB `aiops` |
| redis-ha | sau này nếu cần cache |
| Harbor | `.../aiops/<svc>` |
| Jenkins + Kaniko + SA `jenkins-kaniko` | build image |
| Vault + ESO | secrets |
| Kong | optional Route/service (banking); mặc định OpenShift Route |
| Coroot / Prometheus | endpoints ConfigMap |

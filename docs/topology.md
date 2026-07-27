# Topology & blast radius (Phase 7)

Service dependency graph for correlation, RCA, and Chat Mermaid.

## Sources (priority)

1. **Coroot CE live map** (7B) — `overview/map` + AppMap
2. **Static adjacency** — banking / movie / aiops fallback

## Test trên cluster (sau deploy rca-agent / incident-api / console)

### A. Topology API (7B)

Từ **bastion** không resolve `*.svc` — dùng một trong các cách:

```bash
# 1) Exec vào pod trong cluster (khuyến nghị)
oc exec -n aiops-core deploy/rca-agent -- \
  curl -sS "http://127.0.0.1:8080/api/v1/topology?namespace=npd-movie&workload=movie-api&hops=2" \
  | jq '{source,center,up:(.upstream|length),down:(.downstream|length)}'

# 2) Port-forward
oc -n aiops-core port-forward svc/rca-agent 8080:8080 &
curl -sS "http://127.0.0.1:8080/api/v1/topology?namespace=npd-movie&workload=movie-api&hops=2" | jq .

# 3) Nếu có Route
oc get route -n aiops-core | grep rca
curl -skS "https://rca-agent-aiops-core.apps.ocp01.npd.co/api/v1/topology?namespace=npd-movie&workload=movie-api&hops=2" | jq .
```

In-cluster (từ pod khác) mới dùng được:

```bash
curl -sS "http://rca-agent.aiops-core.svc:8080/api/v1/topology?namespace=npd-movie&workload=movie-api&hops=2"
```

Pass: `source` ∈ `coroot` | `coroot+static` | `static` | `static+coroot-fallback`.  
Có neighbors cho movie/banking. Nếu toàn `coroot-miss` → set `COROOT_PROJECT_ID`.

### B. Incident blast radius (Console)

1. Tạo / mở incident có `namespace` + `workload` (vd. transfer-service).
2. Console → **Incidents** → click row → panel **Blast radius**.
3. Pass: upstream/downstream list (hoặc “No neighbors” nếu workload lạ).

### C. Chat Mermaid (7C)

```bash
curl -skS -X POST https://incident-api-aiops-core.apps.ocp01.npd.co/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"Vẽ luồng app movie","auto_analyze":false}' | jq '{intent, source:.topology.source, mermaid:(.mermaid|.[0:80]), answer:(.answer|.[0:120])}'
```

Console Ask:

| Câu hỏi | Kỳ vọng |
|---------|---------|
| `Vẽ luồng app movie` | intent=`topology`, diagram movie-web/api/worker… |
| `Topology banking` | diagram banking |
| `Vẽ cả cụm OCP` | từ chối + hỏi lại scope |
| Click incident → Blast radius | list neighbors |

### D. Correlation (7B/7.3)

Hai alert khác fingerprint, cùng path (vd. `transfer-service` + `account-service`) trong cửa sổ correlation → gộp 1 incident (`via=topology` trong log).

## APIs

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/topology` (rca-agent) | hops graph |
| `POST /api/v1/topology/related` | related? |
| `GET /api/v1/incidents/{id}/topology` | Console proxy |
| `POST /api/v1/chat` intent `topology` | Mermaid + topology JSON |

## Config

`COROOT_URL`, `COROOT_TOPOLOGY_ENABLED`, `COROOT_PROJECT_ID`, optional `COROOT_EMAIL`/`PASSWORD`.

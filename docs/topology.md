# Topology & blast radius (Phase 7)

Service dependency graph for correlation + RCA enrichment.

## Sources (priority)

1. **Coroot CE live map** (Phase 7B) — `overview/map` + AppMap `clients`/`dependencies`
2. **Static adjacency** — banking / movie / aiops in `rca_agent/topology/graph.py` (fallback / merge)

| Coroot field | AIOps blast-radius |
|--------------|--------------------|
| `downstreams` / `clients` | **upstream** (callers) |
| `upstreams` / `dependencies` | **downstream** (deps) |

## Config (`aiops-endpoints`)

| Env | Purpose |
|-----|---------|
| `COROOT_URL` | In-cluster Coroot base URL |
| `COROOT_TOPOLOGY_ENABLED` | `true`/`false` |
| `COROOT_PROJECT_ID` | Project id from UI (`/p/<id>/…`) — set if `/api/user` không trả projects |
| `COROOT_EMAIL` / `COROOT_PASSWORD` | Optional session login |

## APIs

| Service | Endpoint | Purpose |
|---------|----------|---------|
| rca-agent | `GET /api/v1/topology?namespace=&workload=&hops=2` | Upstream/downstream hops |
| rca-agent | `POST /api/v1/topology/related` | Same topology path? (Coroot+static) |
| incident-api | `GET /api/v1/incidents/{id}/topology` | Console proxy |

Response `source`: `coroot` · `coroot+static` · `static` · `static+coroot-fallback` · `coroot-miss`

## Correlation

Open incidents merge when shared fingerprints **or** related workloads (≤2 hops).

## Next (Phase 7C)

Chat intent “vẽ luồng movie” → Mermaid from the same topology API.

## Demo

```bash
# after deploy rca-agent + set COROOT_PROJECT_ID
curl -sS "http://rca-agent.aiops-core.svc:8080/api/v1/topology?namespace=npd-movie&workload=movie-api&hops=2"
```

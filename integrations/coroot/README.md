# Coroot Integration

Phase 7B: **live service topology** from Coroot CE REST (UI API), not MCP/OAuth.

## Endpoints used

| Path | Use |
|------|-----|
| `POST /api/login` | Optional session (`COROOT_EMAIL` / `COROOT_PASSWORD`) |
| `GET /api/user` | Discover project ids |
| `GET /api/project/{id}/overview/map` | Fleet service map (multi-hop) |
| `GET /api/project/{id}/app/{app_id}` | AppMap `clients` + `dependencies` (1 hop) |

App id forms: `namespace:Kind:name` or `cluster:namespace:Kind:name` (URL-encoded).

## Direction mapping

Coroot names edges from the **application’s** view:

- Coroot **upstreams** = services this app calls → AIOps **downstream**
- Coroot **downstreams** / **clients** = who calls this app → AIOps **upstream**

## Config

See `bootstrap/configmaps/aiops-endpoints.yaml`:

- `COROOT_URL` (required)
- `COROOT_PROJECT_ID` (strongly recommended on lab)
- `COROOT_TOPOLOGY_ENABLED=true`
- Optional login envs

Code: `components/rca-agent/src/rca_agent/topology/coroot_client.py`

## Fallback

If Coroot unreachable / no project / app missing → static lab graph. See [docs/topology.md](../../docs/topology.md).

## Not used (yet)

- MCP `/mcp` (OAuth — better for interactive agents than in-cluster RCA)
- Keep (alert workflow, not service mesh)

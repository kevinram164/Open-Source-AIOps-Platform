# Incident API — Phase 2

FastAPI service: incident CRUD, Alertmanager webhook ingestion, fingerprint correlation.

## Local

```bash
cd components/incident-api
pip install -e ".[dev]"
export DATABASE_URL='postgresql+asyncpg://aiops:pass@localhost:5432/aiops'
uvicorn incident_api.main:create_app --factory --reload --port 8080
```

## Image (Harbor)

```bash
cd components/incident-api
podman build -t harbor-platform.apps.ocp01.npd.co/aiops/incident-api:0.2.0 .
podman push harbor-platform.apps.ocp01.npd.co/aiops/incident-api:0.2.0
```

Helm: `charts/incident-api/`

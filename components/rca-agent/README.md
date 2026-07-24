# RCA Agent — Phase 3

Evidence (K8s events/pods + best-effort Prometheus/Coroot) → OpenAI → structured RCA JSON.

## Build (Jenkins)

`BUILD_TARGET=rca-agent` (or `all`) — pushes `harbor-platform.apps.ocp01.npd.co/aiops/rca-agent:<sha>`.

## API

```
POST /api/v1/analyze
GET  /api/v1/analysis/{incident_id}
GET  /health/ready   # requires OPENAI_API_KEY
```

Trigger via Incident API:

```
POST /api/v1/incidents/{id}/analyze
```

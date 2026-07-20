# RCA Agent

Root Cause Analysis microservice for the Open Source AIOps Platform.

**Phase 1 status**: Skeleton with health endpoints only. Full RCA logic in Phase 3.

## Local development

```bash
cd components/rca-agent
pip install -e ".[dev]"
export OPENAI_API_KEY=sk-...
python -m rca_agent
```

## Endpoints

| Path | Description |
|------|-------------|
| `GET /` | Service info |
| `GET /health/live` | Liveness |
| `GET /health/ready` | Readiness |
| `GET /metrics` | Prometheus metrics |

## Build image

```bash
docker build -t rca-agent:0.1.0-skeleton .
```

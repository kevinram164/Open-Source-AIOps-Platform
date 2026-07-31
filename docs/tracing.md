# App OTLP tracing — shared collector dual-exports to Coroot + Instana (same as banking).
#
# Path:
#   service → opentelemetry-collector.observability:4317 → Coroot + Instana agent

## Checklist for every new app on this lab

1. **Instrument in code** (Python FastAPI example):
   - Gate on `OTEL_EXPORTER_OTLP_ENDPOINT`
   - OTLP gRPC exporter + FastAPI / httpx / SQLAlchemy / Redis as needed
   - Messaging consumers: `SpanKind.CONSUMER` (Instana maps these to services)
   - Add **`setuptools==75.8.2`** (provides `pkg_resources`) — OTEL instrumentation 0.48 needs it; do **not** use setuptools≥82 (removed `pkg_resources`)
2. **Helm / GitOps env** (per service):
   - `OTEL_EXPORTER_OTLP_ENDPOINT=http://opentelemetry-collector.observability.svc.cluster.local:4317`
   - `OTEL_EXPORTER_OTLP_PROTOCOL=grpc`
   - `OTEL_SERVICE_NAME=<service>`
   - `OTEL_RESOURCE_ATTRIBUTES=deployment.environment=dev-ocp,k8s.namespace.name=<ns>,k8s.cluster.name=ocp01`
3. **Reuse the shared collector** in `observability` — do **not** install a new Tempo/Jaeger per app.
4. **Do not** add Instana sidecars unless you deliberately change the model.
5. Static frontends (nginx SPA) can rely on Coroot eBPF + backend OTLP; optional later.

## Reference implementations

| App | Namespace | Services |
|-----|-----------|----------|
| Banking | `npd-banking` | auth, api-producer, account, transfer, notification |
| CineHome | `npd-movie` | movie-api, media-worker |
| AIOps | `aiops-core` / `aiops-automation` | incident-api, rca-agent, remediation-controller |

Banking values: `banking-demo/phase9-gitops-platform/gitops/values-observability.yaml`  
Movie values: `movie-web/gitops/values-observability.yaml`  
AIOps: chart `otel:` block in `charts/*/values.yaml`

## Verify

```bash
# Collector up
oc -n observability get deploy,svc -l app.kubernetes.io/name=opentelemetry-collector

# Env on a pod
oc -n npd-movie set env deploy/movie-api --list | grep OTEL_
oc -n aiops-core set env deploy/incident-api --list | grep OTEL_

# OTEL init in logs (stderr)
oc -n aiops-core logs deploy/incident-api --since=1h | grep '\[otel\]'
oc -n npd-movie logs deploy/movie-api --since=1h | grep '\[otel\]'

# Generate traffic then check collector accepted spans
POD_IP=$(oc -n observability get pod -l app.kubernetes.io/name=opentelemetry-collector -o jsonpath='{.items[0].status.podIP}')
curl -skS https://incident-api-aiops-core.apps.ocp01.npd.co/api/v1/incidents >/dev/null || true
curl -skS https://cinehome.automationecom.click/api/movies >/dev/null || true
oc -n observability run curl-m --rm -i --restart=Never --image=curlimages/curl:8.5.0 -- \
  curl -s "http://${POD_IP}:8888/metrics" | grep otelcol_receiver_accepted_spans
```

### Instana UI (important)

Do **not** filter `Dest Kubernetes Service > name` for OTEL apps — that tag is often empty.

Use instead:

- **Dest Service > Name** equals `incident-api` / `movie-api` / `media-worker` / `rca-agent`
- or **Call > Technology** equals `OpenTelemetry`
- Application Perspective tag: `kubernetes.namespace.name` equals `aiops-core` / `npd-movie` (not `Kubernetes Deployment > namespace`)

Banking shows up because spans carry `service.name` + collector `spanmetrics` + `service.instance.id←pod.uid`. Same path applies here once HTTP spans exist.

## Keep services always visible on Instana

APM map only retains services while recent spans exist. Each app emits `otel.heartbeat` (SERVER) every 30s when OTEL is enabled:

| Env | Default |
|-----|---------|
| `OTEL_HEARTBEAT` | `1` (set `0` to disable) |
| `OTEL_HEARTBEAT_SECONDS` | `30` |

Implemented in: banking `common/observability.py`, movie-api / media-worker, incident-api / rca-agent / remediation-controller, npd-shop.

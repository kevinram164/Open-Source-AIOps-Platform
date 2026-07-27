# App OTLP tracing — shared collector dual-exports to Coroot + Instana (same as banking).
#
# Path:
#   service → opentelemetry-collector.observability:4317 → Coroot + Instana agent

## Checklist for every new app on this lab

1. **Instrument in code** (Python FastAPI example):
   - Gate on `OTEL_EXPORTER_OTLP_ENDPOINT`
   - OTLP gRPC exporter + FastAPI / httpx / SQLAlchemy / Redis as needed
   - Messaging consumers: `SpanKind.CONSUMER` (Instana maps these to services)
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

# Then open Coroot / Instana Application Perspectives for the service name
```

# Resource Sizing Summary

Tài liệu tổng hợp resource requests/limits và persistent storage cho homelab AIOps platform.

## Ngân sách tổng

| Tài nguyên | Mục tiêu | Ghi chú |
|------------|----------|---------|
| CPU requests | 6–8 vCPU | Toàn bộ AIOps layer |
| Memory requests | 16–24 GB | Không tính Coroot |
| Persistent storage | 60–100 GB | Không tính Coroot |

## Per-component sizing (Phase 1–6)

### aiops-core

| Component | CPU req | Mem req | CPU limit | Mem limit | Storage | Phase |
|-----------|---------|---------|-----------|-----------|---------|-------|
| PostgreSQL | 250m | 1Gi | 1 | 3Gi | 20Gi | 2 |
| Redis (optional) | 100m | 256Mi | 500m | 1Gi | — | TBD |
| Incident API | 100m | 256Mi | 500m | 1Gi | — | 2 |
| Event Normalizer | 100m | 256Mi | 500m | 1Gi | — | 2 |
| RCA Agent | 250m | 512Mi | 1 | 2Gi | — | 3 |
| Keep | 200m | 512Mi | 1 | 2Gi | 15Gi | 2 |

### aiops-observability

| Component | CPU req | Mem req | CPU limit | Mem limit | Storage | Phase |
|-----------|---------|---------|-----------|-----------|---------|-------|
| Grafana | 100m | 256Mi | 500m | 1Gi | 5Gi | 5 |

### aiops-automation

| Component | CPU req | Mem req | CPU limit | Mem limit | Storage | Phase |
|-----------|---------|---------|-----------|-----------|---------|-------|
| Remediation Controller | 250m | 512Mi | 1 | 2Gi | — | 4 |
| Argo Workflows controller | 100m | 256Mi | 500m | 1Gi | — | 4 |
| Automation data (workflow artifacts) | — | — | — | — | 15Gi | 4 |

## Tổng hợp requests (ước tính full stack)

| | CPU | Memory | Storage |
|---|-----|--------|---------|
| Minimum (Phase 1 only) | ~0 | ~0 | 0 |
| Phase 2 (+ PG, Keep, APIs) | ~1.0 | ~3.5Gi | ~35Gi |
| Phase 3 (+ RCA Agent) | ~1.25 | ~4Gi | ~35Gi |
| Phase 4 (+ Automation) | ~1.6 | ~5Gi | ~50Gi |
| Phase 5 (+ Grafana) | ~1.7 | ~5.25Gi | ~55Gi |
| **Full stack** | **~1.7–2.0** | **~5.25–6Gi** | **~55–70Gi** |

> Full stack nằm **dưới** ngân sách 6–8 CPU / 16–24 GB, để dư headroom cho spikes và demo workloads.

## Persistent storage breakdown

| PVC | Size | Namespace | StorageClass |
|-----|------|-----------|--------------|
| postgresql-data | 20Gi | aiops-core | configurable |
| keep-data | 15Gi | aiops-core | configurable |
| grafana-data | 5Gi | aiops-observability | configurable |
| automation-artifacts | 15Gi | aiops-automation | configurable |
| **Total** | **~55Gi** | | |

RCA history và audit log lưu trong PostgreSQL — không cần PVC riêng.

## Điều chỉnh khi thiếu tài nguyên

1. **Bỏ Redis** — dùng PostgreSQL cho job queue đơn giản hoặc sync processing.
2. **Giảm Keep storage** — 10Gi nếu ít alert history.
3. **Grafana** — có thể trì hoãn tới Phase 5; dùng Coroot UI tạm thời.
4. **Argo Workflows** — thay bằng Job/CronJob đơn giản cho homelab.
5. **PostgreSQL** — giảm memory request xuống 512Mi nếu cluster chật (không khuyến nghị cho production).

## Điều chỉnh khi có thêm tài nguyên

1. Tăng RCA Agent limits cho LLM context lớn hơn.
2. Thêm Redis cho async RCA queue.
3. PostgreSQL connection pooling (PgBouncer sidecar).
4. HA PostgreSQL (Patroni) — chỉ khi nâng cấp khỏi homelab.

## Monitoring resource usage

```bash
# Xem resource usage theo namespace
oc adm top pods -n aiops-core
oc adm top pods -n aiops-observability
oc adm top pods -n aiops-automation

# Xem requests/limits đã allocate
oc describe quota -n aiops-core
oc get resourcequota -A | grep aiops
```

## Helm values reference

Resource defaults được định nghĩa trong:
- `charts/rca-agent/values.yaml`
- `charts/incident-api/values.yaml` (Phase 2)
- `gitops/environments/homelab/values.yaml`

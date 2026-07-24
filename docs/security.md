# Security Design

## 1. Nguyên tắc

1. **Least privilege** — mỗi component có ServiceAccount riêng, quyền tối thiểu.
2. **Separation of duties** — RCA read-only; automation write qua SA riêng.
3. **No secrets in code/logs** — OpenShift Secret + env injection.
4. **Human approval** — automation không chạy tự động cho action nguy hiểm.
5. **LLM isolation** — LLM chỉ output JSON; không kubectl trực tiếp.

## 2. Service accounts

| ServiceAccount | Namespace | Quyền | Phase |
|--------------|-----------|-------|-------|
| `rca-agent` | aiops-core | ClusterRole read-only (pods, events, deployments, nodes) | 1 |
| `incident-api` | aiops-core | Role namespace-scoped | 2 |
| `remediation-controller` | aiops-automation | Role/ClusterRole write (scoped) | 4 |
| `event-normalizer` | aiops-core | Minimal — no K8s API | 2 |

## 3. RBAC — RCA Agent (Phase 1)

File: `bootstrap/rbac/rca-agent-clusterrole.yaml`

Quyền **read-only**:
- `pods`, `pods/log`, `events`
- `deployments`, `replicasets`, `statefulsets`, `daemonsets`
- `nodes` (read)
- `horizontalpodautoscalers`
- `persistentvolumeclaims`
- `services`, `endpoints`

**Không có**: `create`, `update`, `patch`, `delete` trên bất kỳ resource nào.

## 4. Secrets management

| Secret | Namespace | Keys | Tạo từ |
|--------|-----------|------|--------|
| `openai-api-key` | aiops-core | `OPENAI_API_KEY` | Template + manual apply |
| `postgresql-credentials` | aiops-core | `username`, `password` | Helm/Phase 2 |
| `incident-api-token` | aiops-core | `API_TOKEN` | Phase 2 |

Template: `bootstrap/secrets/openai-api-key.secret.yaml.template`

```bash
# Không commit file secret thật
echo "bootstrap/secrets/*.secret.yaml" >> .gitignore
```

## 5. Network policies

Namespace `aiops-core`:
- **Ingress**: cho phép từ `openshift-monitoring` (Alertmanager webhook), `aiops-observability` (Grafana), trong namespace.
- **Egress**: DNS, OpenShift API, Prometheus, Coroot, OpenAI API (443), PostgreSQL internal.

Chi tiết: `bootstrap/network-policies/`

## 6. OpenShift SCC

- Containers chạy **non-root** với `runAsNonRoot: true`
- Không `privileged`, không `hostNetwork`, không `hostPID`
- `readOnlyRootFilesystem: true` khi ứng dụng hỗ trợ
- Tương thích `restricted-v2` SCC (arbitrary UID)

## 7. LLM safety

```
Alert → Incident API → RCA Agent
                           │
                    Evidence Collector (deterministic)
                           │
                    Summarized context (size-limited)
                           │
                    OpenAI API → JSON schema validation
                           │
                    Policy Engine (allowlist)
                           │
                    Recommendation only (no execution)
```

- Không gửi raw logs vào LLM
- Validate output với Pydantic schema
- `automation_requires_approval: true` mặc định

## 8. Automation safety (Phase 4) — Policy Mode B

**Mode B (đã chọn):** observe + RCA + remediation (có approve) cho **mọi namespace** trừ system/infra deny-list.

- Policy ConfigMap: `aiops-remediation-policy` (`aiops-automation`)
- Deny prefixes: `openshift-`, `kube-`
- Deny namespaces: `default`, `vault`, `argocd`, `harbor`, `postgres`, … (xem ConfigMap)
- Action allowlist: `restart-deployment`, `scale-deployment`
- Approval state machine: `pending → approved → executing → completed/failed`
- AMC sync CronJob: tạo `AlertmanagerConfig/aiops-webhook` tự động trên ns được phép
- Audit: kết quả action lưu trên remediation record (DB audit_log — nâng cấp sau)

### Checklist Mode B

- [ ] Apply `bootstrap/rbac/remediation-rbac.yaml` + policy ConfigMap
- [ ] Verify SA không mutate openshift-*: create remediation với `namespace=openshift-monitoring` → 403
- [ ] Approve bắt buộc trước execute (`requireApproval: true`)
- [ ] AMC sync chạy trên ns app mới trong ≤15 phút

## 9. Audit

Mọi action ghi vào `audit_log` table (PostgreSQL):
- Actor (user, component name)
- Action type
- Resource ID
- Timestamp
- Details (JSON, không chứa secrets)

## 10. Checklist triển khai

- [ ] Apply RBAC trước khi deploy workloads
- [ ] Tạo secrets từ template, không commit
- [ ] Apply NetworkPolicy
- [ ] Verify RCA Agent không có write permissions: `oc auth can-i delete pods --as=system:serviceaccount:aiops-core:rca-agent`
- [ ] Expected: `no`

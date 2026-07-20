# Phase 0 — Discovery Checklist

Chạy các lệnh sau trên OpenShift cluster và gửi output cho agent (Phase tiếp theo). **Không gửi secret values** — chỉ tên secret và keys.

## 1. Cluster overview

```bash
oc version
oc get nodes -o wide
oc get clusterversion
oc get clusteroperator
```

**Expected**: OpenShift 4.x, nodes Ready, cluster operators Available.

## 2. Storage

```bash
oc get storageclass
oc get pv
```

**Cần biết**: StorageClass name cho NFS (dùng trong Helm values), default SC.

## 3. Monitoring stack

```bash
oc get prometheus -A
oc get alertmanager -A
oc get servicemonitor -A --no-headers | wc -l
oc get route -n openshift-monitoring
oc get thanosquerier -A 2>/dev/null || echo "Thanos Querier CR not found"
```

**Cần biết**:
- Prometheus/Alertmanager namespace (thường `openshift-monitoring`)
- Thanos Querier URL hoặc internal service name
- Alertmanager route (nếu expose)

## 4. Coroot

```bash
oc get all -n coroot
oc get pvc -n coroot
oc get route -n coroot
oc get secret -n coroot
oc get configmap -n coroot
```

**Cần biết**:
- Coroot UI/API route hostname
- API port và authentication method
- PVC/storage đã dùng

### Coroot API probe (optional)

```bash
COROOT_ROUTE=$(oc get route -n coroot -o jsonpath='{.items[0].spec.host}' 2>/dev/null)
echo "Coroot route: https://${COROOT_ROUTE}"

# Thử các endpoint phổ biến (điều chỉnh sau khi có docs)
curl -sk "https://${COROOT_ROUTE}/api/health" 2>/dev/null || true
curl -sk "https://${COROOT_ROUTE}/api/v1/projects" 2>/dev/null || true
```

## 5. GitOps (Argo CD)

```bash
oc get applications.argoproj.io -A
oc get pods -n openshift-gitops 2>/dev/null || oc get pods -n argocd 2>/dev/null
oc get route -n openshift-gitops 2>/dev/null || oc get route -n argocd 2>/dev/null
```

**Cần biết**:
- Argo CD namespace
- Argo CD server route
- Repo đã kết nối chưa

## 6. Networking & routes

```bash
oc get route -A | head -30
oc get ingresscontroller -n openshift-ingress-operator
```

## 7. Resource availability

```bash
oc describe nodes | grep -A5 "Allocated resources"
oc get resourcequota -A
oc get limitrange -A
```

## 8. Security context (OpenShift SCC)

```bash
oc get scc | grep -E "restricted|anyuid|nonroot"
```

**Cần biết**: Workloads sẽ dùng `restricted-v2` (mặc định) — arbitrary UID.

## 9. Existing AIOps namespaces

```bash
oc get ns | grep aiops
oc get all -n aiops-core 2>/dev/null
oc get all -n aiops-demo 2>/dev/null
```

## 10. Demo workloads (nếu có)

```bash
oc get deployments -A | grep -E "banking|movie|demo"
oc get servicemonitor -A | grep -E "banking|movie|demo"
```

## Output template

Sau khi chạy, gửi theo format:

```text
## Cluster
- Version: ...
- Nodes: ...
- StorageClass: ...

## Monitoring
- Prometheus NS: ...
- Alertmanager: ...
- Thanos Querier URL: ...

## Coroot
- Namespace: coroot
- Route: ...
- API notes: ...

## Argo CD
- Namespace: ...
- Route: ...

## Notes
- ...
```

## Troubleshooting discovery

| Vấn đề | Giải pháp |
|--------|-----------|
| `oc: command not found` | Cài OpenShift CLI hoặc dùng Cloud Shell |
| Không có quyền xem monitoring | Cần `cluster-monitoring-view` hoặc admin |
| Coroot namespace khác | Cập nhật `bootstrap/configmaps/aiops-endpoints.yaml` |
| Không có Argo CD | Cài OpenShift GitOps Operator trước Phase 1 GitOps sync |

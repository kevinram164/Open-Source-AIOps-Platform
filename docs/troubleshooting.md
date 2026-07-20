# Troubleshooting

## Bootstrap

### PVC stuck in Pending

```bash
oc describe pvc postgresql-data -n aiops-core
oc get storageclass
```

**Fix**: Cập nhật `storageClassName` trong `bootstrap/storage/*.yaml` cho đúng StorageClass của cluster.

### NetworkPolicy blocks traffic

```bash
oc get networkpolicy -n aiops-core
```

**Fix**: Kiểm tra namespace labels. OpenShift DNS namespace phải có label `kubernetes.io/metadata.name: openshift-dns`.

### RCA Agent RBAC

```bash
oc auth can-i delete pods --as=system:serviceaccount:aiops-core:rca-agent
# Expected: no
oc auth can-i get pods --as=system:serviceaccount:aiops-core:rca-agent
# Expected: yes
```

## Argo CD

### Application OutOfSync

```bash
oc get applications.argoproj.io -n openshift-gitops
argocd app diff aiops-bootstrap
```

**Fix**: Cập nhật `repoURL` trong GitOps manifests cho đúng remote repository.

### Argo CD namespace khác `openshift-gitops`

Cập nhật `metadata.namespace` trong tất cả Application manifests.

## Secrets

```bash
oc get secret openai-api-key -n aiops-core
# Nếu NotFound → tạo secret theo bootstrap/secrets/README.md
```

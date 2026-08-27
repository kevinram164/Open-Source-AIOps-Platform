#!/usr/bin/env bash
# Lab OCP: pause Argo + scale 0 AIOps nặng (Ollama 1 CPU, RCA, remediation).
# Không xóa namespace / PVC. Bật lại: oc scale ... --replicas=1 và bật auto-sync Argo.
set -euo pipefail

echo "==> Pause Argo (tránh selfHeal kéo replica lên lại)"
for app in aiops-bootstrap aiops-core aiops-observability aiops-automation aiops-demo aiops-mesh; do
  oc patch application "$app" -n argocd --type=merge \
    -p '{"spec":{"syncPolicy":{"automated":null}}}' 2>/dev/null || true
done

echo "==> Scale 0 workloads AIOps"
for ns in aiops-core aiops-automation aiops-observability aiops-demo; do
  oc get ns "$ns" >/dev/null 2>&1 || continue
  oc -n "$ns" get deploy -o name 2>/dev/null | xargs -r oc -n "$ns" scale --replicas=0
  oc -n "$ns" get sts -o name 2>/dev/null | xargs -r oc -n "$ns" scale --replicas=0
done

echo "==> Còn pod AIOps:"
oc get pod -n aiops-core,aiops-automation,aiops-observability,aiops-demo --no-headers 2>/dev/null || true
echo "Xong. istiod: oc get pod -n istio-system"

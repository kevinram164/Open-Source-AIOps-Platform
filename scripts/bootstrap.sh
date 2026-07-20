#!/usr/bin/env bash
# Bootstrap AIOps platform foundation on OpenShift.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> Applying bootstrap manifests..."
oc apply -k "${REPO_ROOT}/bootstrap/"

echo ""
echo "==> Verifying namespaces..."
oc get ns | grep aiops || true

echo ""
echo "==> Verifying RBAC..."
oc get sa,clusterrole,clusterrolebinding -l app.kubernetes.io/part-of=open-aiops-platform 2>/dev/null || \
  oc get sa -n aiops-core

echo ""
echo "==> Next steps:"
echo "  1. Update StorageClass in bootstrap/storage/*.yaml"
echo "  2. Update endpoints in bootstrap/configmaps/aiops-endpoints.yaml"
echo "  3. Create OpenAI secret: see bootstrap/secrets/README.md"
echo "  4. Apply Argo CD root app: oc apply -f gitops/app-of-apps/homelab-root.yaml"

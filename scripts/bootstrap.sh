#!/usr/bin/env bash
# Register AIOps App of Apps in Argo CD (GitOps entrypoint).
# Do NOT oc apply -k bootstrap/ — Argo Application aiops-bootstrap syncs that path.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> Applying Argo CD root Application (aiops-dev-ocp-root)..."
oc apply -f "${REPO_ROOT}/gitops/app-of-apps/dev-ocp-root.yaml"

echo ""
echo "==> Waiting briefly, then listing AIOps Applications..."
sleep 2
oc get applications.argoproj.io -n argocd | grep -E 'NAME|aiops' || true

echo ""
echo "==> Next steps:"
echo "  1. Ensure repo is pushed: Open-Source-AIOps-Platform @ main"
echo "  2. In Argo UI: sync aiops-dev-ocp-root (auto if enabled)"
echo "  3. aiops-bootstrap will apply namespaces/RBAC/NetPol/PVC/ConfigMaps"
echo "  4. Create OpenAI secret after aiops-core ns exists (Vault/ESO or oc create secret)"
echo "  5. Verify: oc get ns | grep aiops && oc get pvc -A | grep aiops"

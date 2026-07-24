#!/usr/bin/env bash
# Minimal CLI for Chat API demo
set -euo pipefail
BASE="${INCIDENT_API_URL:-https://incident-api-aiops-core.apps.ocp01.npd.co}"
Q="${*:-Why is the service down?}"
curl -skS -X POST "$BASE/api/v1/chat" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg q "$Q" '{question:$q, auto_analyze:true}')" | jq .

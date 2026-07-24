# AIOps Chat API (demo-first)

Natural-language Q&A over incidents / RCA / NBA. **Does not execute** remediations.

## Endpoint

`POST /api/v1/chat` on Incident API  
Swagger: `https://incident-api-aiops-core.apps.ocp01.npd.co/docs`

```bash
curl -skS -X POST https://incident-api-aiops-core.apps.ocp01.npd.co/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "Why is Payment Service down?",
    "namespace": "npd-banking",
    "auto_analyze": true
  }' | jq
```

### Response shape

```json
{
  "answer": "Payment Service is down because ...",
  "evidence": ["...", "..."],
  "recommendation": "Increase memory / restart / gitops-scale ...",
  "probable_root_cause": "...",
  "confidence": 0.7,
  "incident": { "external_id": "INC-...", "namespace": "...", "workload": "..." },
  "nba": { "remediations": [ { "id": "...", "status": "pending" } ] },
  "remediations": [],
  "model": "gpt-4o-mini"
}
```

Approve NBA drafts via remediation-controller (see `docs/runbooks.md`).

## Roadmap

1. Backend + Chat API ← **now**
2. CLI / Swagger testing
3. React AIOps Console (later) consuming the same APIs

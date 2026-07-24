# AIOps Chat — incident investigator

Natural-language ops assistant over incidents / live cluster snapshot / NBA.  
**Does not silently execute** remediations — commands create **pending** drafts for approve → execute.

## Endpoint

`POST /api/v1/chat` on Incident API  
Swagger: `https://incident-api-aiops-core.apps.ocp01.npd.co/docs`  
Console: `https://aiops-console-aiops-core.apps.ocp01.npd.co`

```bash
curl -skS -X POST https://incident-api-aiops-core.apps.ocp01.npd.co/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "Why is Payment Service down?",
    "namespace": "npd-banking",
    "auto_analyze": true
  }' | jq
```

## Intents

| Intent | Example | Behavior |
|--------|---------|----------|
| `investigate` | Why is Payment / transfer-service down? | Resolve **workload** (not namespace-only), run/load RCA, return symptom vs root cause |
| `ops_query` | Có điều gì đáng lưu ý? Có CrashLoopBackOff? Node nào Ready=False? | Live snapshot via RCA agent `/api/v1/ops/snapshot` |
| `command_restart` | restart pod X / restart transfer-service in npd-banking | Create **pending** `restart-deployment` (approve to run) |
| `general` | mixed | Prefer incident bind; else ops snapshot |

## Response shape (investigator)

```json
{
  "intent": "investigate",
  "answer": "...",
  "evidence": ["waiting.message=...", "Event ..."],
  "recommendation": "...",
  "symptom": "Containers reporting ImagePullBackOff",
  "symptom_confidence": 0.9,
  "probable_root_cause": "Cannot pull image ...",
  "root_cause_confidence": 0.7,
  "confidence": 0.8,
  "error_subtype": "ImagePullBackOff",
  "impact_scope": {
    "namespaces": ["npd-banking"],
    "workloads": ["transfer-service"],
    "pods": ["transfer-service-..."],
    "nodes": [],
    "blast_radius": "service"
  },
  "incident": { "external_id": "INC-...", "workload": "transfer-service" },
  "nba": { "remediations": [] },
  "remediations": [],
  "ops_snapshot": null,
  "model": "gpt-4o-mini"
}
```

### Accuracy pipeline (ordered)

1. Resolve correct service/workload from the question  
2. Pick incident by workload score (not namespace-only smoke)  
3. Collect full `waiting.message` + event messages  
4. Separate symptom vs root cause  
5. Separate `symptom_confidence` / `root_cause_confidence`  
6. NBA / remediation by `error_subtype` (ImagePull → no restart; CrashLoop → restart; OOM → gitops-scale; Node → ansible)  
7. Structured `impact_scope`

## Ops Q&A vs remediation commands

- **Q&A** (“pod nào crashloop?”, “đáng lưu ý không?”) → read-only snapshot.  
- **Command** (“restart pod A”) → **yes, supported**: creates pending remediation; you approve in Console / remediation API. Policy Mode B still applies (observe-deny / remediation-deny namespaces).

## Related

- `docs/runbooks.md` — approve & execute NBA  
- RCA agent: `POST /api/v1/ops/snapshot`, `POST /api/v1/analyze`

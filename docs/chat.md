# AIOps Chat — Phase 6 platform ops assistant

Day-2 ops Q&A over a **platform context pack** + optional multi-turn **session memory**.  
Commands like restart create **pending** remediations — never silent auto-run.

## Endpoint

`POST /api/v1/chat`

```bash
# First turn (creates session_id)
curl -skS -X POST https://incident-api-aiops-core.apps.ocp01.npd.co/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"Pods nào đang cao tải nhất?"}' | jq '{session_id,answer,suggested_followups}'

# Follow-up (pass session_id)
curl -skS -X POST https://incident-api-aiops-core.apps.ocp01.npd.co/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"Còn pod nào nữa?","session_id":"<from-previous>"}' | jq
```

## Phase 6 capabilities

| Item | Behavior |
|------|----------|
| Context pack | metrics, failures, inventory, **Warning events, PVC not Bound, HPA at max** |
| Evidence normalize | never char-by-char list |
| `session_id` | last ~10 turns in Postgres `chat_turns` |
| `suggested_followups` | rule-based next questions |
| Audit | every user/assistant turn stored |
| LLM | `LLM_PROVIDER=ollama` → `qwen2.5:3b` (or openai) |

## Intent model

| Intent | When |
|--------|------|
| `ops_query` | **Default** |
| `investigate` | why / down / RCA |
| `command_restart` | restart … |

## Deploy notes

```bash
oc apply -f bootstrap/rbac/rca-agent-monitoring-view.yaml
oc apply -f bootstrap/configmaps/aiops-platform-config.yaml
# rebuild incident-api + rca-agent + aiops-console
```

See also: [ollama.md](ollama.md) · [roadmap.md](roadmap.md)

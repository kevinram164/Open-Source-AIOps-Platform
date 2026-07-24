# AIOps Chat — general platform ops assistant

Ask **many different** day-2 questions. The backend does **not** route each question
to a hardcoded topic handler. Instead:

1. Gather one **platform context pack** (metrics, nodes, failures, inventory, recent incidents)
2. Let the LLM answer **that exact question** from the pack
3. Only special-case: restart command → pending remediation; clear “why down” → RCA

## Endpoint

`POST /api/v1/chat`

Examples that should all work after deploy (same code path):

- Pods nào đang cao tải nhất?
- Node nào Ready=False?
- Deployment nào trong npd-banking chưa ready?
- Có CrashLoopBackOff không?
- Có điều gì đáng lưu ý không?
- Incident nào đang open?
- Why is Payment Service down?  *(investigate + RCA)*
- restart transfer-service in npd-banking  *(pending remediation)*

## Architecture

```
question
   ├─ command_restart  → create pending remediation
   ├─ investigate      → bind incident + RCA (+ NBA)
   └─ ops_query (default)
         → RCA POST /api/v1/ops/context   # multi-facet pack
         → + recent incidents from DB
         → OpenAI selects relevant facts → answer
```

No per-topic if/else for every new question type. Extending capability =
enriching the context pack (new collectors), not adding chat branches.

## Console

https://aiops-console-aiops-core.apps.ocp01.npd.co

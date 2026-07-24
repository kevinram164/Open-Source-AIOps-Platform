# Remediation Controller — Phase 4 (Policy Mode B)

Observe+RCA+remediation with **human approval** for all namespaces except system/infra deny-list.

## API

```
GET  /api/v1/policy
POST /api/v1/remediations
POST /api/v1/remediations/{id}/approve
POST /api/v1/remediations/{id}/execute
```

Actions: `restart-deployment`, `scale-deployment`.

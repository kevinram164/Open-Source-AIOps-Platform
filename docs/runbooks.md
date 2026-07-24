# Runbooks — Remediation (Phase 4, Policy Mode B)

## Approve + restart deployment

```bash
# 1) Tạo yêu cầu
curl -sS -X POST https://remediation-controller-aiops-automation.apps.ocp01.npd.co/api/v1/remediations \
  -H 'Content-Type: application/json' \
  -d '{
    "incident_id": "INC-XXXX",
    "action": "restart-deployment",
    "namespace": "npd-banking",
    "target": "frontend",
    "reason": "RCA recommends restart after ImagePullBackOff resolved",
    "requested_by": "oncall"
  }'

# 2) Approve (thay REM_ID)
curl -sS -X POST "https://remediation-controller-aiops-automation.apps.ocp01.npd.co/api/v1/remediations/REM_ID/approve?approved_by=kevin"

# 3) Execute
curl -sS -X POST "https://remediation-controller-aiops-automation.apps.ocp01.npd.co/api/v1/remediations/REM_ID/execute"
```

## Scale deployment

```bash
curl -sS -X POST https://remediation-controller-aiops-automation.apps.ocp01.npd.co/api/v1/remediations \
  -H 'Content-Type: application/json' \
  -d '{
    "action": "scale-deployment",
    "namespace": "npd-movie",
    "target": "phim-web",
    "parameters": {"replicas": 2},
    "reason": "recover from crashloop pressure"
  }'
# rồi approve → execute như trên
```

## Policy check

```bash
curl -sS https://remediation-controller-aiops-automation.apps.ocp01.npd.co/api/v1/policy
```

Namespace trong deny-list / `openshift-*` / `kube-*` → HTTP 403.

## AMC auto-onboard (Mode B)

CronJob `remediation-controller-amc-sync` mỗi 15 phút tạo `AlertmanagerConfig/aiops-webhook` trên mọi ns không bị deny → alert → Incident API tự động cho project mới.

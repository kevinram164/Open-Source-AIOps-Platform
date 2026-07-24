# Alertmanager → Incident API

Webhook URL (in-cluster):

```text
http://incident-api.aiops-core.svc:8080/api/v1/alerts
```

## OpenShift user-workload / platform Alertmanager

Tạo `AlertmanagerConfig` trong namespace muốn forward (ví dụ `openshift-monitoring` hoặc app ns). Preview:

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata:
  name: aiops-webhook
  namespace: openshift-monitoring
  labels:
    alertmanagerConfig: aiops
spec:
  route:
    receiver: aiops-webhook
    groupBy: ['namespace', 'alertname']
    groupWait: 30s
    groupInterval: 5m
    repeatInterval: 4h
  receivers:
    - name: aiops-webhook
      webhookConfigs:
        - url: 'http://incident-api.aiops-core.svc:8080/api/v1/alerts'
          sendResolved: true
```

> Trên OCP, `AlertmanagerConfig` thường cần label selector khớp Alertmanager. Kiểm tra:
> `oc get alertmanager -n openshift-monitoring -o yaml | grep -A5 alertmanagerConfig`

## Test thủ công

```bash
oc exec -n aiops-core deploy/incident-api -- \
  curl -sS -X POST http://127.0.0.1:8080/api/v1/alerts \
  -H 'Content-Type: application/json' \
  -d '{"status":"firing","alerts":[{"fingerprint":"test1","labels":{"alertname":"Test","namespace":"banking-demo","severity":"warning"},"annotations":{"summary":"test alert"}}]}'
```

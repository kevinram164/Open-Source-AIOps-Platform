# Alertmanager Integration

Phase 2: cấu hình webhook receiver gửi alert tới Event Normalizer / Incident API.

```yaml
# Preview — AlertmanagerConfig receiver
receivers:
  - name: aiops-webhook
    webhook_configs:
      - url: 'http://event-normalizer.aiops-core.svc:8080/api/v1/alerts'
        send_resolved: true
```

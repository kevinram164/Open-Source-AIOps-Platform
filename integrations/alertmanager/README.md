# Alertmanager → Incident API

Webhook (in-cluster):

```text
http://incident-api.aiops-core.svc.cluster.local:8080/api/v1/alerts
```

## GitOps overlays

| Overlay | Namespace | Alerts covered |
|---------|-----------|----------------|
| `overlays/npd-banking` | `npd-banking` | Alert có `namespace=npd-banking` |
| `overlays/npd-movie` | `npd-movie` | Alert có `namespace=npd-movie` |
| `overlays/openshift-monitoring` | `openshift-monitoring` | Alert platform |

Argo apps: `aiops-alertmanager-*` (qua `aiops-observability`).

## Policy Mode B — auto-onboard

Khi **Mode B** bật, CronJob `remediation-controller-amc-sync` (ns `aiops-automation`) mỗi 15 phút tạo/cập nhật `AlertmanagerConfig/aiops-webhook` trên mọi namespace **không** nằm trong deny-list. Overlay banking/movie vẫn dùng được; sync sẽ đồng bộ cùng webhook URL.

Deny-list: ConfigMap `aiops-remediation-policy` (`openshift-*`, `kube-*`, vault, argocd, harbor, …).

## 1) Bật User AlertmanagerConfig (OCP) — qua Argo

ConfigMap `cluster-monitoring-config` nằm trong overlay GitOps:

`integrations/alertmanager/overlays/openshift-monitoring/cluster-monitoring-config.yaml`

Argo app: **`aiops-alertmanager-platform`** (path overlay trên). Sync app này trước (hoặc cùng) banking/movie.

```bash
# Sau push Git
oc get application aiops-alertmanager-platform -n argocd
# Sync trong UI nếu Missing — cần quyền vào ns openshift-monitoring

oc get cm cluster-monitoring-config -n openshift-monitoring -o yaml
oc get alertmanagerconfig -n openshift-monitoring
```

Nếu AppProject `default` chặn destination `openshift-monitoring`, whitelist ns đó hoặc apply một lần:

```bash
oc apply -k integrations/alertmanager/overlays/openshift-monitoring
```

Đợi operator reconcile (~1–2 phút) rồi kiểm tra:

```bash
oc get alertmanager main -n openshift-monitoring \
  -o jsonpath='{.spec.alertmanagerConfigSelector}{"\n"}{.spec.alertmanagerConfigNamespaceSelector}{"\n"}'
```

## 2) Deploy configs

```bash
# Sau push Git — sync Argo, hoặc apply local:
oc apply -k integrations/alertmanager/overlays/npd-banking
oc apply -k integrations/alertmanager/overlays/npd-movie
# platform (cần quyền):
oc apply -k integrations/alertmanager/overlays/openshift-monitoring

oc get alertmanagerconfig -A | grep aiops
```

NetPol `aiops-core` phải cho ingress từ `openshift-monitoring` (đã có trong bootstrap).

## 3) Test thủ công (không cần Alertmanager)

```bash
oc exec -n aiops-core deploy/incident-api -- python -c "
import json, urllib.request
payload = {
  'status': 'firing',
  'alerts': [{
    'fingerprint': 'manual-test-1',
    'labels': {
      'alertname': 'AiopsManualTest',
      'namespace': 'npd-banking',
      'severity': 'warning',
      'deployment': 'api-producer',
    },
    'annotations': {'summary': 'AIOps webhook smoke test'},
  }],
}
req = urllib.request.Request(
  'http://127.0.0.1:8080/api/v1/alerts',
  data=json.dumps(payload).encode(),
  headers={'Content-Type': 'application/json'},
  method='POST',
)
print(urllib.request.urlopen(req).read().decode())
"

curl -sk https://incident-api-aiops-core.apps.ocp01.npd.co/api/v1/incidents
```

## 4) Verify Alertmanager đã gửi

```bash
# Log Alertmanager (tìm webhook / incident-api)
oc logs -n openshift-monitoring -l app.kubernetes.io/name=alertmanager --tail=100 | grep -iE 'incident-api|webhook|error'

curl -sk https://incident-api-aiops-core.apps.ocp01.npd.co/api/v1/incidents
```

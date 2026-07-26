# Ollama LLM for Open Source AIOps Platform (GitOps)

Chat / RCA use `LLM_PROVIDER=ollama` → `http://ollama.aiops-core.svc:11434`, model `qwen2.5:3b`.

## OpenShift: one loop, two errors — fix without SCC

| Error | Cause | Wrong fix | Right fix |
|--|--|--|--|
| `mkdir /.ollama: permission denied` | Random UID, no home → ollama uses `/.ollama` | `runAsUser: 0` | Mount **emptyDir** at `/.ollama` |
| SCC / PodSecurity reject `runAsUser: 0` | `aiops-core` is **restricted** | Custom SCC / anyuid | Stay non-root; never set UID 0 |

Manifest annotation: `aiops.platform/ollama-datadir: v8-num-parallel-1`.

Lab trade-off: emptyDir + pull `qwen2.5:3b` on start (reschedule = re-pull ~2GB).

## Argo CD

Application **`aiops-ollama`** → path `bootstrap/ollama`.

```bash
# Sync v6
argocd app sync aiops-ollama --force --prune
# or: oc apply -f bootstrap/ollama/ollama.yaml

oc -n aiops-core get deploy ollama -o jsonpath='{.metadata.annotations.aiops\.platform/ollama-datadir}{"\n"}'
# expect: v8-num-parallel-1

oc -n aiops-core get deploy ollama -o yaml | grep -E 'runAsUser|mountPath|fix-perms' || true
# expect mountPath: /.ollama — NO runAsUser: 0 — NO fix-perms

oc -n aiops-core rollout status deploy/ollama --timeout=15m
oc -n aiops-core logs -l app.kubernetes.io/name=ollama -c ollama -f
# expect: Waiting for ollama API... / Pulling qwen2.5:3b ...
oc -n aiops-core exec deploy/ollama -- ollama list
```

Cleanup leftovers from earlier attempts:

```bash
oc -n aiops-core delete job -l app.kubernetes.io/name=ollama --ignore-not-found
oc -n aiops-core delete scc ollama-fs --ignore-not-found
oc -n aiops-core delete pvc ollama-data --ignore-not-found
```

## Config

```yaml
LLM_PROVIDER: "ollama"
OLLAMA_BASE_URL: "http://ollama.aiops-core.svc:11434"
OLLAMA_MODEL: "qwen2.5:3b"
```

### Chat `ERR_EMPTY_RESPONSE` @ đúng 2 phút

Browser Network: **Time = 2 min** + `net::ERR_EMPTY_RESPONSE` dù Route = 300s.  
Có hop khác (LB / proxy) cắt ~120s. Nếu LLM treo 180–300s → client **không nhận** cả fallback.

**Nguyên tắc:** ops + LLM phải xong **trước 120s** → `OLLAMA_TIMEOUT_SECONDS=75`, ops context ~25s, không kịp thì trả **template 200** (có PVC/disk facts).

Ngay trên cluster (không chờ rebuild):

```bash
oc -n aiops-core set env deploy/incident-api OLLAMA_TIMEOUT_SECONDS=45
# Ask lại trong <2 phút — phải thấy HTTP 200 (có thể badge template), không Failed to fetch
```

Rồi rebuild `incident-api` (+ optional console) từ commit mới để có deadline cứng + PVC fallback đẹp hơn.

## Resources

| | |
|--|--|
| emptyDir @ `/.ollama` | 20Gi |
| requests | 1 CPU / 4Gi |
| limits | 4 CPU / 12Gi |

# Ollama LLM for Open Source AIOps Platform (GitOps)

Chat / RCA use `LLM_PROVIDER=ollama` → `http://ollama.aiops-core.svc:11434`, model `qwen2.5:3b`.

## Why emptyDir (not PVC) on this lab

`aiops-core` enforces PodSecurity **restricted** → **cannot** `runAsUser: 0`.  
NFS PVC then often returns `permission denied` for arbitrary UIDs.

Lab choice: **emptyDir 20Gi** (always writable) + **pull `qwen2.5:3b` on container start**.  
Trade-off: reschedule pod = re-pull model (~2GB, a few minutes).

## Argo CD

Application **`aiops-ollama`** → path `bootstrap/ollama`.

```bash
git pull
oc -n aiops-core delete job ollama-pull-qwen25-3b --ignore-not-found
oc -n aiops-core delete scc ollama-fs --ignore-not-found
oc apply -f bootstrap/ollama/ollama.yaml
oc -n aiops-core rollout status deploy/ollama --timeout=10m
oc -n aiops-core logs -l app.kubernetes.io/name=ollama -c ollama -f
# expect: Pulling qwen2.5:3b ... then Ready
oc -n aiops-core exec deploy/ollama -- ollama list
```

First start can take **several minutes** while the model downloads (startupProbe allows ~10m).

## Config

```yaml
LLM_PROVIDER: "ollama"
OLLAMA_BASE_URL: "http://ollama.aiops-core.svc:11434"
OLLAMA_MODEL: "qwen2.5:3b"
```

## Resources

| | |
|--|--|
| emptyDir | 20Gi |
| requests | 1 CPU / 4Gi |
| limits | 4 CPU / 8Gi |

## Optional later: persistent PVC

Needs either namespace PSA `baseline`/`privileged` **or** NFS `mountPermissions: "0777"` + non-root writable volume — then remount PVC at `/var/lib/ollama` and drop the start-up pull if models already present.

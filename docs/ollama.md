# Ollama LLM for Open Source AIOps Platform (GitOps)

Chat (incident-api) and RCA (rca-agent) use **`LLM_PROVIDER=ollama|openai`**.

## OpenShift notes

Pods run as **non-root**. Do **not** mount at `/root/.ollama` without `HOME` —
Ollama then tries `mkdir /.ollama` → CrashLoop (`permission denied`).

Lab fix in manifests:

```yaml
env:
  - name: HOME
    value: /ollama
volumeMounts:
  - name: models
    mountPath: /ollama   # data → /ollama/.ollama on PVC
```

## Argo CD (lab)

Application **`aiops-ollama`** (under `aiops-core` app-of-apps):

| Field | Value |
|-------|--------|
| Path | `bootstrap/ollama` |
| Namespace | `aiops-core` |
| Sync wave | `2` (before incident-api / rca-agent) |
| Resources | PVC `ollama-models` 40Gi, Deployment, Service, Route, Job pull |

PostSync Job **`ollama-pull-qwen25-3b`** runs:

```text
OLLAMA_HOST=http://ollama.aiops-core.svc:11434
ollama pull qwen2.5:3b
```

After push to `main`, Argo syncs automatically (selfHeal). Re-pull model:

```bash
oc -n aiops-core delete job ollama-pull-qwen25-3b --ignore-not-found
# then Sync aiops-ollama in Argo (hook recreates Job)
```

Verify:

```bash
oc -n aiops-core get deploy,svc,pvc,job -l app.kubernetes.io/name=ollama
oc -n aiops-core logs job/ollama-pull-qwen25-3b
oc -n aiops-core exec deploy/ollama -- ollama list
```

## Config

`aiops-platform-config`:

```yaml
LLM_PROVIDER: "ollama"
OLLAMA_BASE_URL: "http://ollama.aiops-core.svc:11434"
OLLAMA_MODEL: "qwen2.5:3b"
```

## Resources (3B CPU lab)

| | |
|--|--|
| PVC | 40Gi models |
| Deploy requests | 1 CPU / 4Gi |
| Deploy limits | 4 CPU / 8Gi |
| Model disk | ~2Gi for qwen2.5:3b |

## Switch back to OpenAI

Set `LLM_PROVIDER=openai` + secret `openai-api-key`, restart rca-agent / incident-api.

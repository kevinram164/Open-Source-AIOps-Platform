# Secret templates — DO NOT commit files with real values.

## OpenAI API Key

```bash
cp openai-api-key.secret.yaml.template openai-api-key.secret.yaml
# Edit and replace CHANGE_ME with your API key
oc apply -f openai-api-key.secret.yaml
```

Or create directly:

```bash
oc create secret generic openai-api-key \
  --namespace=aiops-core \
  --from-literal=OPENAI_API_KEY='sk-...' \
  --dry-run=client -o yaml | oc apply -f -
```

## PostgreSQL credentials (Phase 2)

```bash
oc create secret generic postgresql-credentials \
  --namespace=aiops-core \
  --from-literal=username=aiops \
  --from-literal=password='$(openssl rand -base64 24)' \
  --dry-run=client -o yaml | oc apply -f -
```

## Verification

```bash
oc get secret -n aiops-core
# Should show openai-api-key (after apply) — never print secret values
```

package com.aiops

class VaultClient implements Serializable {

    static Map readKv2(def steps, Map cfg, String secretPath) {
        def vaultAddr = (cfg.vaultAddr ?: 'http://vault.vault.svc.cluster.local:8200').replaceAll('/$', '')
        def role = cfg.vaultRole ?: 'jenkins-kaniko'

        def loginScript = '''#!/bin/bash
set -euo pipefail
JWT=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT
CODE=$(curl -sS -o "$BODY" -w "%{http_code}" --request POST \\
  --data-urlencode "jwt=${JWT}" \\
  --data-urlencode "role=''' + role + '''" \\
  "''' + vaultAddr + '''/v1/auth/kubernetes/login")
cat "$BODY"
if [ "$CODE" != "200" ]; then
  echo "Vault kubernetes login HTTP $CODE (role=''' + role + ''')" >&2
  exit 22
fi
'''
        def loginRaw = steps.sh(script: loginScript, returnStdout: true).trim()
        def login = steps.readJSON(text: loginRaw)
        if (!login?.auth?.client_token) {
            steps.error("Vault login missing client_token: ${loginRaw}")
        }
        def clientToken = login.auth.client_token.toString()

        def secretScript = '''#!/bin/bash
set -euo pipefail
BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT
CODE=$(curl -sS -o "$BODY" -w "%{http_code}" \\
  -H "X-Vault-Token: ''' + clientToken + '''" \\
  "''' + vaultAddr + '''/v1/secret/data/''' + secretPath + '''")
cat "$BODY"
if [ "$CODE" != "200" ]; then
  echo "Vault read secret/''' + secretPath + ''' HTTP $CODE" >&2
  exit 22
fi
'''
        def secretRaw = steps.sh(script: secretScript, returnStdout: true).trim()
        def secret = steps.readJSON(text: secretRaw)
        if (!secret?.data?.data) {
            steps.error("Vault secret/${secretPath} empty: ${secretRaw}")
        }
        return secret.data.data as Map
    }

    static Map harborCredentials(def steps, Map cfg) {
        def path = cfg.vaultHarborPath ?: 'aiops/harbor'
        def data = readKv2(steps, cfg, path)
        if (!data.username || !data.password) {
            steps.error("Vault secret/${path} missing username/password")
        }
        return [username: data.username.toString(), password: data.password.toString()]
    }

    static Map githubCredentials(def steps, Map cfg) {
        def path = cfg.vaultGithubPath ?: 'platform/github'
        def data = readKv2(steps, cfg, path)
        def user = data.username ?: data.github_username
        def token = data.pat ?: data.github_pat ?: data.password
        if (!user || !token) {
            steps.error("Vault secret/${path} missing username/pat")
        }
        return [username: user.toString(), token: token.toString()]
    }
}

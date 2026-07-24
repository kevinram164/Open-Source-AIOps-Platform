package com.aiops

class GitOpsUpdater implements Serializable {

    static void bumpImageTags(def steps, Map cfg, List<String> services) {
        def tag = GitRef.imageTag(steps)
        def file = cfg.gitopsValuesFile

        services.each { svc ->
            def meta = PipelineConfig.SERVICES[svc]
            def helmKey = meta.helmKey
            steps.sh """
                set -e
                sed -i '/^${helmKey}:/,/^[^ ]/ s/^  tag: .*/  tag: \"${tag}\"/' ${file} || true
            """
        }

        def github = VaultClient.githubCredentials(steps, cfg)
        steps.withEnv([
            "GIT_USER=${github.username}",
            "GIT_TOKEN=${github.token}",
        ]) {
            steps.sh """
                set -e
                git config user.email "jenkins@aiops.local"
                git config user.name "Jenkins CI"
                git add ${file}
                if git diff --cached --quiet; then
                  echo 'GitOps values unchanged'
                  exit 0
                fi
                git commit -m "ci: bump image tags to ${tag} [${services.join(', ')}]"
                export GIT_TERMINAL_PROMPT=0
                git push "https://x-access-token:\${GIT_TOKEN}@${cfg.gitRepoUrl.replaceFirst('^https://', '')}" HEAD:${cfg.gitBranch}
            """
        }
        steps.echo "Updated ${file} — ArgoCD will sync."
    }
}

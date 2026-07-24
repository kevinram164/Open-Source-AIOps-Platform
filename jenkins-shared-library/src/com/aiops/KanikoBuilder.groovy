package com.aiops

class KanikoBuilder implements Serializable {

    static void buildAndPush(def steps, Map cfg, String serviceName) {
        def meta = PipelineConfig.SERVICES[serviceName]
        if (!meta) {
            steps.error("Unknown service: ${serviceName}")
        }
        def tag = GitRef.imageTag(steps)
        def image = "${cfg.harborHost}/${cfg.harborProject}/${serviceName}:${tag}"
        def extras = ['--cache=false', '--cleanup', '--ignore-path=/busybox', '--ignore-path=/kaniko', '--ignore-path=/home/jenkins']
        if (cfg.kanikoSkipTlsVerify) {
            extras << '--skip-tls-verify'
        }
        extras << "--snapshot-mode=${meta.snapshotMode ?: 'time'}"
        def extraFlags = extras.join(' ')
        def contextDir = meta.context ?: '.'
        def df = meta.dockerfile.contains('/') ? meta.dockerfile.tokenize('/').last() : meta.dockerfile

        def harbor = VaultClient.harborCredentials(steps, cfg)
        steps.withEnv([
            "HARBOR_USER=${harbor.username}",
            "HARBOR_PASS=${harbor.password}",
            'DOCKER_CONFIG=/home/jenkins/agent/.docker',
        ]) {
            steps.container(name: 'kaniko', shell: '/home/jenkins/agent/bin/sh') {
                def rc = steps.sh(
                    returnStatus: true,
                    script: """
                    set -e
                    mkdir -p "\${DOCKER_CONFIG}"
                    set +x
                    AUTH=\$(printf '%s:%s' "\${HARBOR_USER}" "\${HARBOR_PASS}" | base64 | tr -d '\\n')
                    printf '%s\\n' "{\\"auths\\":{\\"${cfg.harborHost}\\":{\\"auth\\":\\"\$AUTH\\"}}}" > "\${DOCKER_CONFIG}/config.json"
                    set -x
                    /kaniko/executor \\
                      --context=dir://\$(pwd)/${contextDir} \\
                      --dockerfile=${df} \\
                      --destination=${image} \\
                      ${extraFlags}
                    echo "KANIKO_PUSH_OK ${image}"
                    """,
                )
                if (rc != 0 && rc != -1) {
                    steps.error("Kaniko build ${serviceName} failed (exit ${rc})")
                }
            }
        }
        steps.echo "Pushed ${image}"
    }
}

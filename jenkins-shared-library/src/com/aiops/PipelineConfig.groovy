package com.aiops

class PipelineConfig implements Serializable {

    static final Map SERVICES = [
        'incident-api': [
            dockerfile       : 'Dockerfile',
            context          : 'components/incident-api',
            helmKey          : 'image',
            watchPath        : 'components/incident-api',
            snapshotMode     : 'full',
            gitopsValuesFile : 'gitops/values-images-incident-api.yaml',
        ],
        'rca-agent': [
            dockerfile       : 'Dockerfile',
            context          : 'components/rca-agent',
            helmKey          : 'image',
            watchPath        : 'components/rca-agent',
            snapshotMode     : 'full',
            gitopsValuesFile : 'gitops/values-images-rca-agent.yaml',
        ],
        'remediation-controller': [
            dockerfile       : 'Dockerfile',
            context          : 'components/remediation-controller',
            helmKey          : 'image',
            watchPath        : 'components/remediation-controller',
            snapshotMode     : 'full',
            gitopsValuesFile : 'gitops/values-images-remediation-controller.yaml',
        ],
    ]

    static Map mergeDefaults(Map user) {
        def defaults = [
            harborHost         : 'harbor-platform.apps.ocp01.npd.co',
            harborProject      : 'aiops',
            gitBranch          : 'main',
            gitRepoUrl         : 'https://github.com/kevinram164/Open-Source-AIOps-Platform.git',
            gitopsValuesFile   : 'gitops/values-images-incident-api.yaml',
            kanikoImage        : 'gcr.io/kaniko-project/executor:v1.23.2-debug',
            kanikoSkipTlsVerify: true,
            kanikoUseCache     : false,
            vaultAddr          : 'http://vault.vault.svc.cluster.local:8200',
            vaultRole          : 'jenkins-kaniko',
            vaultHarborPath    : 'aiops/harbor',
            vaultGithubPath    : 'platform/github',
        ]
        return defaults + user
    }
}

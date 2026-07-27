@Library('platform@main') _

// BUILD_TARGET: auto | all | incident-api | rca-agent | remediation-controller | aiops-console
// Central library: https://github.com/kevinram164/jenkins-shared-library

platformPipeline([
  project             : 'aiops',
  harborHost          : 'harbor-platform.apps.ocp01.npd.co',
  harborProject       : 'aiops',
  gitBranch           : 'main',
  gitRepoUrl          : 'https://github.com/kevinram164/Open-Source-AIOps-Platform.git',
  vaultAddr           : 'http://vault.vault.svc.cluster.local:8200',
  vaultRole           : 'jenkins-kaniko',
  vaultHarborPath     : 'aiops/harbor',
  vaultGithubPath     : 'platform/github',
  kanikoSkipTlsVerify : true,
])

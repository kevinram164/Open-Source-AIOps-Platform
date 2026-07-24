@Library('aiops@main') _

// BUILD_TARGET: auto | all | incident-api | rca-agent | remediation-controller
// Reuse Jenkins SA jenkins-kaniko + Vault + Harbor (giống banking/movie)

aiopsPipeline([
  harborHost          : 'harbor-platform.apps.ocp01.npd.co',
  harborProject       : 'aiops',
  gitBranch           : 'main',
  gitRepoUrl          : 'https://github.com/kevinram164/Open-Source-AIOps-Platform.git',
  gitopsValuesFile    : 'gitops/values-images.yaml',
  vaultAddr           : 'http://vault.vault.svc.cluster.local:8200',
  vaultRole           : 'jenkins-kaniko',
  vaultHarborPath     : 'aiops/harbor',
  vaultGithubPath     : 'platform/github',
  kanikoSkipTlsVerify : true,
])

#!groovy
def call(Map config = [:]) {
    setupParameters()
    def cfg = com.aiops.PipelineConfig.mergeDefaults(config)

    podTemplate(
        yamlMergeStrategy: merge(),
        yaml: """
apiVersion: v1
kind: Pod
spec:
  serviceAccountName: jenkins-kaniko
  containers:
    - name: jnlp
      env:
        - name: HOME
          value: /home/jenkins/agent
      workingDir: /home/jenkins/agent
      volumeMounts:
        - name: home-jenkins
          mountPath: /home/jenkins
    - name: kaniko
      image: ${cfg.kanikoImage}
      command: ["/busybox/busybox"]
      args:
        - "sh"
        - "-c"
        - "mkdir -p /home/jenkins/agent/bin && cp /busybox/busybox /home/jenkins/agent/bin/sh && cp /busybox/busybox /home/jenkins/agent/bin/busybox && exec /busybox/busybox sleep 99d"
      tty: true
      env:
        - name: PATH
          value: "/home/jenkins/agent/bin:/busybox:/kaniko:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      securityContext:
        runAsUser: 0
        runAsGroup: 0
        runAsNonRoot: false
        allowPrivilegeEscalation: false
      volumeMounts:
        - name: home-jenkins
          mountPath: /home/jenkins
  volumes:
    - name: home-jenkins
      emptyDir: {}
""") {
        node(POD_LABEL) {
            stage('Checkout') {
                checkout scm
                env.GIT_COMMIT = sh(script: 'git rev-parse HEAD', returnStdout: true).trim()
            }

            def targets = com.aiops.ChangeDetector.resolve(this, cfg)
            if (targets.isEmpty()) {
                echo 'No services selected — done.'
                currentBuild.result = 'SUCCESS'
                return
            }

            targets.each { svc ->
                stage("Build ${svc}") {
                    com.aiops.KanikoBuilder.buildAndPush(this, cfg, svc)
                }
            }

            stage('Update GitOps') {
                com.aiops.GitOpsUpdater.bumpImageTags(this, cfg, targets)
            }
        }
    }
}

def setupParameters() {
    properties([
        parameters([
            choice(
                name: 'BUILD_TARGET',
                choices: com.aiops.ChangeDetector.buildTargetChoices(),
                description: 'auto | all | incident-api',
            ),
        ]),
    ])
}

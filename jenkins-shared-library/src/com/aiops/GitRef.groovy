package com.aiops

class GitRef implements Serializable {
    static String imageTag(def steps) {
        def fromEnv = steps.env.GIT_COMMIT?.take(7)
        if (fromEnv) {
            return fromEnv
        }
        return steps.sh(script: 'git rev-parse --short=7 HEAD', returnStdout: true).trim()
    }
}

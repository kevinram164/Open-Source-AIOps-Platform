package com.aiops

class ChangeDetector implements Serializable {

    static List buildTargetChoices() {
        def services = PipelineConfig.SERVICES.keySet().sort() as List
        return ['auto', 'all'] + services
    }

    static List resolve(def steps, Map cfg) {
        def target = steps.params.BUILD_TARGET ?: 'auto'
        if (target == 'all') {
            return PipelineConfig.SERVICES.keySet().sort() as List
        }
        if (target != 'auto' && PipelineConfig.SERVICES.containsKey(target)) {
            return [target]
        }
        def changed = steps.sh(
            script: 'git diff --name-only HEAD~1 HEAD 2>/dev/null || git ls-files',
            returnStdout: true,
        ).trim().readLines()
        def hit = [] as Set
        PipelineConfig.SERVICES.each { name, meta ->
            def watch = meta.watchPath
            changed.each { path ->
                if (path.startsWith("${watch}/") || path == "${watch}/Dockerfile") {
                    hit << name
                }
            }
        }
        if (hit.isEmpty() && (steps.env.FORCE_BUILD_ALL == 'true' || target == 'auto')) {
            steps.echo 'No path match — build all required services'
            return PipelineConfig.SERVICES.keySet().sort() as List
        }
        return hit.sort() as List
    }
}

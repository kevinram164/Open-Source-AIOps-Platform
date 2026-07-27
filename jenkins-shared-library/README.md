# Moved

Canonical Jenkins shared library is now a **standalone repo**:

https://github.com/kevinram164/jenkins-shared-library

Use `@Library('platform@main')` + `platformPipeline(project: 'aiops', …)`.

This nested copy is deprecated — do not register it as a separate Jenkins library.

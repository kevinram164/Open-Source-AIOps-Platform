{{- define "aiops-console.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "aiops-console.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- include "aiops-console.name" . }}
{{- end }}
{{- end }}

{{- define "aiops-console.labels" -}}
app.kubernetes.io/name: {{ include "aiops-console.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: open-aiops-platform
app.kubernetes.io/component: console
{{- end }}

{{- define "aiops-console.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aiops-console.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

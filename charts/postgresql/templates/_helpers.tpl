{{- define "postgresql.fullname" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "postgresql.labels" -}}
app.kubernetes.io/name: {{ include "postgresql.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: open-aiops-platform
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "postgresql.selectorLabels" -}}
app.kubernetes.io/name: {{ include "postgresql.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

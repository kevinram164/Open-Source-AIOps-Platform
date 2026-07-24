{{- define "incident-api.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "incident-api.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "incident-api.labels" -}}
helm.sh/chart: {{ include "incident-api.name" . }}-{{ .Chart.Version | replace "+" "_" }}
{{ include "incident-api.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: open-aiops-platform
{{- end }}

{{- define "incident-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "incident-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

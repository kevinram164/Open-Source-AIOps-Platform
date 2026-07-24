{{- define "remediation-controller.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "remediation-controller.fullname" -}}
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

{{- define "remediation-controller.labels" -}}
helm.sh/chart: {{ include "remediation-controller.name" . }}-{{ .Chart.Version | replace "+" "_" }}
{{ include "remediation-controller.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: open-aiops-platform
aiops.platform/policy-mode: "B"
{{- end }}

{{- define "remediation-controller.selectorLabels" -}}
app.kubernetes.io/name: {{ include "remediation-controller.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

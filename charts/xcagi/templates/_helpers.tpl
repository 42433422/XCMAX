{{- define "xcagi.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "xcagi.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- printf "%s" $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "xcagi.labels" -}}
app.kubernetes.io/name: {{ include "xcagi.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app: xcagi
version: v3.0
{{- end }}

{{- define "xcagi.selectorLabels" -}}
app: xcagi
{{- end }}

{{- define "xcagi.tenantLabels" -}}
xcagi.io/tenant: {{ .Values.tenancy.tenantId | quote }}
{{- end }}

{{- define "xcagi.namespace" -}}
{{- if and .Values.namespace.create .Values.namespace.name }}
{{- .Values.namespace.name }}
{{- else }}
{{- .Release.Namespace }}
{{- end }}
{{- end }}

{{- define "xcagi.image" -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- end }}

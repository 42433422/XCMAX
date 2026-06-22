{{/*
Namespace the chart deploys into.
*/}}
{{- define "xcagi.namespace" -}}
{{- default "xcagi-staging" .Values.global.namespace -}}
{{- end -}}

{{/*
Chart name (sanitized to <= 63 chars, DNS-safe).
*/}}
{{- define "xcagi.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Chart label value: "<name>-<version>".
*/}}
{{- define "xcagi.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels applied to every rendered object.
*/}}
{{- define "xcagi.labels" -}}
helm.sh/chart: {{ include "xcagi.chart" . }}
{{ include "xcagi.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Selector labels (stable across upgrades — never include version here).
*/}}
{{- define "xcagi.selectorLabels" -}}
app.kubernetes.io/name: {{ include "xcagi.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Image reference helper. Pass a dict: (dict "repository" "x" "tag" "y").
Falls back to "latest" when tag is empty.
*/}}
{{- define "xcagi.image" -}}
{{- printf "%s:%s" .repository (default "latest" .tag) -}}
{{- end -}}

{{/*
Name of the Secret holding sensitive API config (admin creds, DB creds, API keys).
Uses secrets.existingSecret when provided, otherwise the chart-managed "xcagi-secrets".
*/}}
{{- define "xcagi.secretName" -}}
{{- default "xcagi-secrets" .Values.secrets.existingSecret -}}
{{- end -}}

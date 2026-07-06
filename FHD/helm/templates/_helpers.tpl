{{/*
Common labels for xcagi resources.
*/}}
{{- define "xcagi-fhd-api.labels" -}}
app: xcagi
component: fhd-api
version: "10.0.0"
{{- end -}}

{{/*
Selector labels for xcagi resources.
*/}}
{{- define "xcagi-fhd-api.selectorLabels" -}}
app: xcagi
component: fhd-api
{{- end -}}

{{/*
Full image reference: repo:tag
*/}}
{{- define "xcagi-fhd-api.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag }}
{{- end -}}

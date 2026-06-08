{{- define "xcagi.namespace" -}}
{{- default "xcagi-staging" .Values.global.namespace -}}
{{- end -}}

import { primeCsrfCookie } from '@/api/core'
import { apiFetch } from '@/utils/apiBase'

export type EtlAction = 'new' | 'update' | 'skip' | 'error'

export type EtlFieldMapping = {
  source: string
  target: string
  transforms: Record<string, unknown>[]
  confidence: number
  required: boolean
}

export type EtlValidationIssue = {
  code: string
  message: string
  severity: 'info' | 'warning' | 'error'
  field: string
}

export type EtlTargetField = {
  key: string
  label: string
  type: string
  required: boolean
  aliases: string[]
  updatable: boolean
}

export type EtlTargetCapability = {
  type: string
  label: string
  fields: EtlTargetField[]
  required_fields: string[]
  default_match_keys: string[]
  supported_actions: EtlAction[]
  reversible: boolean
  allow_dynamic_fields?: boolean
}

export type EtlCapabilities = {
  enabled: boolean
  limits: { max_file_bytes: number; max_rows: number }
  inputs: {
    structured: string[]
    ocr: string[]
    knowledge_only: string[]
    folder_upload?: boolean
  }
  transforms: string[]
  targets: EtlTargetCapability[]
  compatibility_presets?: Array<{ id: string; label: string; source: string; target: string }>
  execution_policy: Record<string, unknown>
}

export type EtlRun = {
  id: string
  upload_id: string
  file_name: string
  batch_id?: string | null
  relative_path?: string
  file_sha256: string
  template_id?: string | null
  template_version_id?: string | null
  target_type: string
  status: string
  stage: string
  progress: number
  total_rows: number
  processed_rows: number
  summary: { new: number; update: number; skip: number; error: number; executed: number }
  details: Record<string, unknown>
  source_features: Record<string, unknown>
  draft: {
    field_mappings?: EtlFieldMapping[]
    validation_rules?: Record<string, unknown>[]
    match_keys?: string[]
    allowed_update_fields?: string[]
    action_rules?: Record<string, unknown>
    target_config_id?: string
    ocr_confirmed?: boolean
  }
  receipt: Record<string, unknown>
  reversible: boolean
  rollback_status?: string | null
  error?: { code: string; message: string } | null
  created_at?: string | null
  updated_at?: string | null
  executed_at?: string | null
}

export type EtlUploadOptions = {
  batchId?: string
  relativePath?: string
}

export type EtlRunRow = {
  id: number
  source_sheet: string
  source_row: number
  source: Record<string, unknown>
  normalized: Record<string, unknown>
  provenance: Record<string, unknown>
  validation_issues: EtlValidationIssue[]
  llm_suggestion: {
    action?: EtlAction
    reason?: string
    used_llm?: boolean
    advisory_only?: boolean
  }
  suggested_action: EtlAction
  final_action: EtlAction
  action_overridden: boolean
  match_ref?: string | null
  before: Record<string, unknown>
  after: Record<string, unknown>
  execution_status?: string | null
  execution_error?: { code: string; message: string } | null
}

export type EtlTemplate = {
  id: string
  name: string
  description?: string | null
  target_type: string
  current_version: number
  version: {
    id: string
    number: number
    source_features: Record<string, unknown>
    field_mappings: EtlFieldMapping[]
    validation_rules: Record<string, unknown>[]
    match_keys: string[]
    allowed_update_fields: string[]
    action_rules: Record<string, unknown>
    created_at?: string | null
  }
}

export type EtlTargetConfig = {
  id: string
  name: string
  target_type: 'webhook'
  endpoint_url: string
  headers: Record<string, string>
  has_secret: boolean
  is_active: boolean
}

type ApiEnvelope<T> = { success: boolean; data: T }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = String(init.method || 'GET').toUpperCase()
  if (!['GET', 'HEAD'].includes(method)) await primeCsrfCookie()
  const res = await apiFetch(path, init)
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body?.success === false) {
    const detail = body?.detail || body || {}
    const message = String(detail.message || body?.message || `请求失败 HTTP ${res.status}`)
    const error = new Error(message) as Error & { code?: string; status?: number }
    error.code = String(detail.code || body?.error_code || 'ETL_REQUEST_FAILED')
    error.status = res.status
    throw error
  }
  return (body as ApiEnvelope<T>).data
}

export const etlApi = {
  capabilities: () => request<EtlCapabilities>('/api/etl/capabilities'),
  upload: async (file: File, options: EtlUploadOptions = {}) => {
    const form = new FormData()
    form.append('file', file)
    if (options.batchId) form.append('batch_id', options.batchId)
    if (options.relativePath) form.append('relative_path', options.relativePath)
    return request<{
      upload_id: string
      file_name: string
      batch_id?: string | null
      relative_path?: string
      suffix: string
      size_bytes: number
      sha256: string
    }>('/api/etl/uploads', { method: 'POST', body: form })
  },
  preview: (body: {
    upload_id: string
    target_type: string
    template_id?: string
    compatibility_preset_id?: string
    target_config_id?: string
    llm_advice_enabled?: boolean
  }) =>
    request<EtlRun>('/api/etl/runs/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  batchAdvice: (body: {
    source_label: string
    items: Array<{
      file_name: string
      target_type: string
      database_target_label: string
      confidence: number
      sheet_count: number
      row_count: number
      new_count: number
      update_count: number
      skip_count: number
      error_count: number
      template_count: number
      knowledge_ready: boolean
      database_recommended: boolean
      warnings: string[]
    }>
  }) =>
    request<{
      used_llm: boolean
      advisory_only: boolean
      degraded: boolean
      degradation_code?: string
      model?: string
      advice: {
        overall_judgment?: string
        reasoning?: string[]
        cautions?: string[]
        questions?: string[]
      }
    }>('/api/etl/batch-advice', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  runs: (limit = 50, batchId = '') =>
    request<EtlRun[]>(`/api/etl/runs?limit=${limit}${batchId ? `&batch_id=${encodeURIComponent(batchId)}` : ''}`),
  run: (id: string) => request<EtlRun>(`/api/etl/runs/${encodeURIComponent(id)}`),
  rows: (id: string, page = 1, pageSize = 50, action = '') =>
    request<{ page: number; page_size: number; total: number; items: EtlRunRow[] }>(
      `/api/etl/runs/${encodeURIComponent(id)}/rows?page=${page}&page_size=${pageSize}${action ? `&action=${encodeURIComponent(action)}` : ''}`,
    ),
  patchDraft: (id: string, body: Record<string, unknown>) =>
    request<EtlRun>(`/api/etl/runs/${encodeURIComponent(id)}/draft`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  execute: (id: string, validRowsOnly = false) =>
    request<EtlRun>(`/api/etl/runs/${encodeURIComponent(id)}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmed: true, valid_rows_only: validRowsOnly }),
    }),
  saveShipmentTemplate: (id: string, name = '', sourceRegionId = '') =>
    request<{
      template_id: string
      name: string
      file_path: string
      source_region_id?: string
      message: string
    }>(`/api/etl/runs/${encodeURIComponent(id)}/shipment-template`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        ...(sourceRegionId ? { source_region_id: sourceRegionId } : {}),
      }),
    }),
  retry: (id: string) => request<EtlRun>(`/api/etl/runs/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
  rollback: (id: string) => request<EtlRun>(`/api/etl/runs/${encodeURIComponent(id)}/rollback`, { method: 'POST' }),
  deleteTemplate: async (id: string) => {
    await primeCsrfCookie()
    const normalized = id.startsWith('etl:') ? id.slice(4) : id
    const res = await apiFetch(`/api/etl/templates/${encodeURIComponent(normalized)}`, { method: 'DELETE' })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      const detail = body?.detail || body || {}
      throw new Error(String(detail.message || body?.message || `模板回滚失败 HTTP ${res.status}`))
    }
    return true
  },
  templates: () => request<EtlTemplate[]>('/api/etl/templates'),
  createTemplate: (body: {
    name: string
    target_type: string
    draft: Record<string, unknown>
    source_features?: Record<string, unknown>
    description?: string
  }) =>
    request<EtlTemplate>('/api/etl/templates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  targetConfigs: () => request<EtlTargetConfig[]>('/api/etl/targets'),
  createTargetConfig: (body: { name: string; endpoint_url: string; headers?: Record<string, string>; secret?: string }) =>
    request<EtlTargetConfig>('/api/etl/targets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateTargetConfig: (
    id: string,
    body: {
      name: string
      endpoint_url: string
      headers?: Record<string, string>
      secret?: string
    },
  ) =>
    request<EtlTargetConfig>(`/api/etl/targets/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  testTarget: (id: string) =>
    request<Record<string, unknown>>(`/api/etl/targets/${encodeURIComponent(id)}/test`, {
      method: 'POST',
    }),
  exportUrl: (id: string) => `/api/etl/runs/${encodeURIComponent(id)}/download`,
  errorExportUrl: (id: string) => `/api/etl/runs/${encodeURIComponent(id)}/errors/export`,
}

export default etlApi

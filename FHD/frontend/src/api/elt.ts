import { primeCsrfCookie } from '@/api/core'
import { apiFetch } from '@/utils/apiBase'

export type EltAction = 'new' | 'update' | 'skip' | 'error'

export type EltFieldMapping = {
  source: string
  target: string
  transforms: Record<string, unknown>[]
  confidence: number
  required: boolean
}

export type EltValidationIssue = {
  code: string
  message: string
  severity: 'info' | 'warning' | 'error'
  field: string
}

export type EltTargetField = {
  key: string
  label: string
  type: string
  required: boolean
  aliases: string[]
  updatable: boolean
}

export type EltTargetCapability = {
  type: string
  label: string
  fields: EltTargetField[]
  required_fields: string[]
  default_match_keys: string[]
  supported_actions: EltAction[]
  reversible: boolean
  allow_dynamic_fields?: boolean
}

export type EltCapabilities = {
  enabled: boolean
  limits: { max_file_bytes: number; max_rows: number }
  inputs: {
    structured: string[]
    ocr: string[]
    knowledge_only: string[]
    folder_upload?: boolean
  }
  transforms: string[]
  targets: EltTargetCapability[]
  compatibility_presets?: Array<{ id: string; label: string; source: string; target: string }>
  execution_policy: Record<string, unknown>
}

export type EltRun = {
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
  preview_revision?: string | null
  stage: string
  progress: number
  total_rows: number
  processed_rows: number
  summary: { new: number; update: number; skip: number; error: number; executed: number }
  details: Record<string, unknown>
  source_features: Record<string, unknown>
  draft: {
    field_mappings?: EltFieldMapping[]
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

export type EltRunRow = {
  id: number
  source_sheet: string
  source_row: number
  source: Record<string, unknown>
  normalized: Record<string, unknown>
  provenance: Record<string, unknown>
  validation_issues: EltValidationIssue[]
  llm_suggestion: {
    action?: EltAction
    reason?: string
    used_llm?: boolean
    advisory_only?: boolean
  }
  suggested_action: EltAction
  final_action: EltAction
  action_overridden: boolean
  match_ref?: string | null
  before: Record<string, unknown>
  after: Record<string, unknown>
  execution_status?: string | null
  execution_error?: { code: string; message: string } | null
}

export type EltTemplate = {
  id: string
  name: string
  description?: string | null
  target_type: string
  current_version: number
  version: {
    id: string
    number: number
    source_features: Record<string, unknown>
    field_mappings: EltFieldMapping[]
    validation_rules: Record<string, unknown>[]
    match_keys: string[]
    allowed_update_fields: string[]
    action_rules: Record<string, unknown>
    created_at?: string | null
  }
}

export type EltTargetConfig = {
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
    error.code = String(detail.code || body?.error_code || 'ELT_REQUEST_FAILED')
    error.status = res.status
    throw error
  }
  return (body as ApiEnvelope<T>).data
}

export const eltApi = {
  run: (id: string) => request<EltRun>(`/api/elt/runs/${encodeURIComponent(id)}`),
  autoIngest: (body: {
    source_path: string
    file_name?: string
    template_id?: string
    review_id?: string
    classification_id?: string
    composer_note?: string
    labels?: string[]
  }) =>
    request<Record<string, unknown>>('/api/elt/auto-ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  autoIngestBatches: (limit = 50, mine = true) =>
    request<Array<Record<string, unknown>>>(
      `/api/elt/auto-ingest/batches?limit=${limit}&mine=${mine ? 'true' : 'false'}`,
    ),
  withdrawAutoIngestBatch: (batchId: string) =>
    request<Record<string, unknown>>(
      `/api/elt/auto-ingest/batches/${encodeURIComponent(batchId)}/withdraw`,
      { method: 'POST' },
    ),
  autoIngestProgress: (batchId: string) =>
    request<{
      batch_id: string
      status?: string
      kb_progress?: { stage?: string; pct?: number; message?: string; error?: string }
      business_progress?: { stage?: string; pct?: number; message?: string; error?: string }
      updated_at?: string
    }>(`/api/elt/auto-ingest/batches/${encodeURIComponent(batchId)}/progress`),
}

export default eltApi

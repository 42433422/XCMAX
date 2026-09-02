import { stripGridPreviewData, stripSampleRowsKeepTemplateShape } from '@/shared/templatePreviewSanitize.js'
import type { TplPreviewData } from './tpTemplateMeta'

/** 归一化后的模板字段（label 非空；type 沿用后端原值，缺省 dynamic） */
export interface NormalizedTemplateField {
  label: string
  value: string
  type: unknown
}

/** 模板保存/替代载荷（fields + 脱敏后的 preview_data） */
export interface TemplatePayload {
  fields: NormalizedTemplateField[]
  preview_data: Record<string, unknown>
}

/** sessionStorage 中的 Excel 分析上下文（宽松 JSON 结构） */
export interface ExcelAnalysisContext {
  fields?: unknown
  preview_data?: TplPreviewData
  [key: string]: unknown
}

const EXCEL_ANALYSIS_STORAGE_PREFIX = 'xcagi_excel_analysis_ctx_'

/** 单个原始字段的宽松读取视图（后端字段可能缺失或非对象） */
type LooseField = { label?: unknown; name?: unknown; type?: unknown }

function toLooseField(field: unknown): LooseField {
  return field && typeof field === 'object' ? (field as LooseField) : {}
}

export function getLatestExcelAnalysisContext(): ExcelAnalysisContext | null {
  try {
    const activeSessionId = String(localStorage.getItem('ai_session_id') || '').trim()
    const sessionKey = activeSessionId || 'default'
    const raw = sessionStorage.getItem(EXCEL_ANALYSIS_STORAGE_PREFIX + sessionKey)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return parsed as ExcelAnalysisContext
  } catch (e) {
    console.warn('读取 Excel 分析上下文失败:', e)
    return null
  }
}

export function normalizeExcelAnalysisFields(rawFields: unknown): NormalizedTemplateField[] {
  const fields = Array.isArray(rawFields) ? rawFields : []
  return fields
    .map((field): NormalizedTemplateField | null => {
      const f = toLooseField(field)
      const label = String(f.label || f.name || '').trim()
      if (!label) return null
      return {
        label,
        value: '',
        type: f.type || 'dynamic'
      }
    })
    .filter((field): field is NormalizedTemplateField => Boolean(field))
}

export function buildTemplatePayloadFromExcelAnalysis(): TemplatePayload | null {
  const ctx = getLatestExcelAnalysisContext()
  if (!ctx) return null
  const rawFields = Array.isArray(ctx?.fields) ? ctx.fields : []
  const previewData: TplPreviewData = ctx?.preview_data || {}
  const normalizedFields = normalizeExcelAnalysisFields(rawFields)
  if (!normalizedFields.length) return null

  const strippedSampleRows = stripSampleRowsKeepTemplateShape(previewData?.sample_rows, normalizedFields)
  const strippedGridPreview = stripGridPreviewData(previewData?.grid_preview, previewData?.sample_rows)
  return {
    fields: normalizedFields,
    preview_data: {
      ...previewData,
      sample_rows: strippedSampleRows,
      grid_preview: strippedGridPreview
    }
  }
}

export function sanitizeFieldsKeepTemplateShape(rawFields: unknown): NormalizedTemplateField[] {
  const normalized = normalizeExcelAnalysisFields(rawFields)
  if (normalized.length) return normalized
  const fallback = Array.isArray(rawFields) ? rawFields : []
  return fallback
    .map((field): NormalizedTemplateField | null => {
      const f = toLooseField(field)
      const label = String(f.label || f.name || '').trim()
      if (!label) return null
      return {
        label,
        value: '',
        type: f.type || 'dynamic'
      }
    })
    .filter((field): field is NormalizedTemplateField => Boolean(field))
}

export function buildTemplatePayloadFromSourceTemplate(tpl: TplRecordInput | null): TemplatePayload | null {
  if (!tpl || tpl.category !== 'excel') return null
  const sourceFields = Array.isArray(tpl.fields) ? tpl.fields : []
  const sourcePreview: TplPreviewData = tpl.preview_data && typeof tpl.preview_data === 'object'
    ? tpl.preview_data
    : {}
  const sanitizedFields = sanitizeFieldsKeepTemplateShape(sourceFields)
  if (!sanitizedFields.length) return null

  const strippedSampleRows = stripSampleRowsKeepTemplateShape(
    sourcePreview.sample_rows,
    sanitizedFields
  )
  const strippedGridPreview = stripGridPreviewData(
    sourcePreview.grid_preview,
    sourcePreview.sample_rows
  )
  return {
    fields: sanitizedFields,
    preview_data: {
      ...sourcePreview,
      sample_rows: strippedSampleRows,
      grid_preview: strippedGridPreview
    }
  }
}

/** 源模板入参（允许 TplRecord 或任意带 fields/preview_data 的松散对象） */
type TplRecordInput = {
  category?: unknown
  fields?: unknown
  preview_data?: TplPreviewData | null
  [key: string]: unknown
}

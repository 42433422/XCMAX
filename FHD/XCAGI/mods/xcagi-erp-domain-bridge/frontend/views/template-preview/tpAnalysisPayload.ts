import { stripGridPreviewData, stripSampleRowsKeepTemplateShape } from '@/shared/templatePreviewSanitize.js'

const EXCEL_ANALYSIS_STORAGE_PREFIX = 'xcagi_excel_analysis_ctx_'

export function getLatestExcelAnalysisContext(): any {
  try {
    const activeSessionId = String(localStorage.getItem('ai_session_id') || '').trim()
    const sessionKey = activeSessionId || 'default'
    const raw = sessionStorage.getItem(EXCEL_ANALYSIS_STORAGE_PREFIX + sessionKey)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return parsed
  } catch (e) {
    console.warn('读取 Excel 分析上下文失败:', e)
    return null
  }
}

export function normalizeExcelAnalysisFields(rawFields: any): any[] {
  const fields = Array.isArray(rawFields) ? rawFields : []
  return fields
    .map((field: any) => {
      const label = String(field?.label || field?.name || '').trim()
      if (!label) return null
      return {
        label,
        value: '',
        type: field?.type || 'dynamic'
      }
    })
    .filter(Boolean)
}

export function buildTemplatePayloadFromExcelAnalysis(): any {
  const ctx = getLatestExcelAnalysisContext()
  if (!ctx) return null
  const rawFields = Array.isArray(ctx?.fields) ? ctx.fields : []
  const previewData = ctx?.preview_data || {}
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

export function sanitizeFieldsKeepTemplateShape(rawFields: any): any[] {
  const normalized = normalizeExcelAnalysisFields(rawFields)
  if (normalized.length) return normalized
  const fallback = Array.isArray(rawFields) ? rawFields : []
  return fallback
    .map((field: any) => {
      const label = String(field?.label || field?.name || '').trim()
      if (!label) return null
      return {
        label,
        value: '',
        type: field?.type || 'dynamic'
      }
    })
    .filter(Boolean)
}

export function buildTemplatePayloadFromSourceTemplate(tpl: any): any {
  if (!tpl || tpl.category !== 'excel') return null
  const sourceFields = Array.isArray(tpl.fields) ? tpl.fields : []
  const sourcePreview = tpl.preview_data && typeof tpl.preview_data === 'object'
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

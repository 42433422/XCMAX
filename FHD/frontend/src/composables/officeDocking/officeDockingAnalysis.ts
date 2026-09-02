/**
 * 办公对接分析结果与知识库文本构建（拆分自 composables/useChatOfficeDocking.ts，行为保持一致）：
 * CSV / Excel 读取结果映射为 excelAnalysis，PPT 文本拼接，知识库文本组装。
 */
import { mapOfficeExcelReadToAnalysisResult, type OfficeFileUploadResult } from '@/utils/officeEmployeeReadApi'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import { stringifyPreview, truncate } from './officeDockingShared'

function rowsToGrid(columns: string[], rows: Record<string, unknown>[]): unknown[][] {
  return [columns, ...rows.slice(0, 20).map((row) => columns.map((col) => row[col] ?? ''))]
}

export function buildCsvExcelAnalysis(upload: OfficeFileUploadResult, csvData: Record<string, unknown>, summary: string): Record<string, unknown> {
  const columns = asArray<unknown>(csvData.columns)
    .map((c) => asString(c).trim())
    .filter(Boolean)
  const rows = asArray<Record<string, unknown>>(csvData.rows).map((row) => asRecord(row))
  const sheet = {
    sheet_index: 1,
    sheet_name: upload.filename || 'CSV',
    fields: columns.map((name) => ({ name, label: name, type: 'dynamic' })),
    sample_rows: rows.slice(0, 50),
    grid_preview: { rows: rowsToGrid(columns, rows) },
    tables: [],
  }
  return {
    file_name: upload.filename,
    file_path: upload.file_path,
    summary,
    fields: columns,
    preview_data: {
      sheet_name: sheet.sheet_name,
      sheet_names: [sheet.sheet_name],
      file_path: upload.file_path,
      sample_rows: sheet.sample_rows,
      grid_preview: sheet.grid_preview,
      all_sheets: [sheet],
    },
    sheets: [sheet],
    excel_import_use_deterministic_shortcut: true,
  }
}

export function buildWorkbookExcelAnalysis(
  upload: OfficeFileUploadResult,
  workbookData: Record<string, unknown>,
  summary: string,
): Record<string, unknown> {
  const mapped = mapOfficeExcelReadToAnalysisResult(upload, workbookData)
  return {
    file_name: upload.filename,
    file_path: upload.file_path,
    summary,
    fields: mapped.fields || [],
    preview_data: mapped.preview_data || {},
    sheets: mapped.sheets || [],
    excel_import_use_deterministic_shortcut: true,
  }
}

export function buildPptText(jsonData: Record<string, unknown>): string {
  const title = asString(jsonData.title || jsonData.source).trim()
  const slides = asArray<Record<string, unknown>>(jsonData.slides)
  const lines = title ? [`# ${title}`] : []
  for (const slide of slides.slice(0, 80)) {
    const index = asString(slide.index || '').trim()
    const heading = asString(slide.title || '').trim()
    const texts = asArray<unknown>(slide.texts || slide.body || slide.shapes)
      .map((item) => {
        if (typeof item === 'string') return item
        const row = asRecord(item)
        return asString(row.text || row.content || row.name)
      })
      .filter(Boolean)
      .join('\n')
    lines.push(`第 ${index || lines.length} 页 ${heading}`.trim())
    if (texts) lines.push(texts)
    const notes = asString(slide.notes_generated || slide.notes_existing).trim()
    if (notes) lines.push(`备注：${notes}`)
  }
  return truncate(lines.join('\n'), 12_000) || stringifyPreview(jsonData, 12_000)
}

export function buildKnowledgeText(item: {
  fileName: string
  employeeLabel: string
  kindLabel: string
  intentLabel: string
  intentSummary: string
  summary: string
  fieldNames: string[]
  sampleRows: Record<string, unknown>[]
  textPreview: string
}): string {
  const lines = [
    `文件：${item.fileName}`,
    `类型：${item.kindLabel}`,
    `识别员工：${item.employeeLabel}`,
    item.intentLabel ? `业务意图：${item.intentLabel}` : '',
    item.intentSummary ? `意图说明：${item.intentSummary}` : '',
    item.summary ? `识别摘要：${item.summary}` : '',
  ].filter(Boolean)
  if (item.fieldNames.length) lines.push(`字段：${item.fieldNames.join('、')}`)
  if (item.sampleRows.length) lines.push(`样例行：\n${stringifyPreview(item.sampleRows, 4000)}`)
  if (item.textPreview) lines.push(`正文预览：\n${truncate(item.textPreview, 8000)}`)
  return lines.join('\n')
}

import { computed, ref } from 'vue'
import { primeCsrfCookie } from '@/api/core'
import {
  CSV_FULL_READ_EMPLOYEE_ID,
  EXCEL_FULL_READ_EMPLOYEE_ID,
  PDF_FULL_READ_EMPLOYEE_ID,
  PPT_FULL_READ_EMPLOYEE_ID,
  WORD_FULL_READ_EMPLOYEE_ID,
} from '@/constants/officeEmployeePack'
import { apiFetch } from '@/utils/apiBase'
import {
  isOfficeDockingFileSupported,
  mapOfficeExcelReadToAnalysisResult,
  readOfficeEmployeeOutputs,
  resolveOfficeReadEmployeeForFile,
  runOfficeEmployeeRead,
  uploadChatOfficeFile,
  type OfficeEmployeeOutputFile,
  type OfficeFileUploadResult,
} from '@/utils/officeEmployeeReadApi'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import type { ChatDecisionOption } from '@/types/chat-ui'

type OfficeDockingTarget = 'template' | 'database'
type OfficeDockingStatus = 'running' | 'ready' | 'error'
type OfficeDockingCommitStatus = '' | 'committing' | 'committed' | 'failed' | 'skipped'
type OfficeDockingIntentId =
  | 'pending'
  | 'attendance_roster'
  | 'attendance_source'
  | 'shipment_delivery'
  | 'customer_product'
  | 'generic_table'
  | 'document'
type OfficeDockingDatabaseAction = '' | 'attendance_import' | 'shipment_etl_execute' | 'customer_product_import'

export type ShipmentEtlNotePreview = {
  sheet_name?: string
  unit_name?: string
  item_count?: number
  total_amount?: number
  items?: Record<string, unknown>[]
  [key: string]: unknown
}

export type ShipmentEtlPreview = {
  success?: boolean
  note_count?: number
  notes?: ShipmentEtlNotePreview[]
  message?: string
  product_records?: Record<string, unknown>[]
  duplicate_note_count?: number
  ledger_risk?: boolean
  ledger_available_count?: number
  [key: string]: unknown
}

export type ChatOfficeDockingReviewItem = {
  id: string
  fileName: string
  employeeId: string
  employeeLabel: string
  kindLabel: string
  status: OfficeDockingStatus
  commitStatus: OfficeDockingCommitStatus
  intentId: OfficeDockingIntentId
  intentLabel: string
  intentSummary: string
  databaseTargetLabel: string
  databaseAction: OfficeDockingDatabaseAction
  databaseDisabledReason: string
  selectedTemplate: boolean
  selectedDatabase: boolean
  templateName: string
  templateScope: string
  templateTargetLabel: string
  templateCommitStatus: OfficeDockingCommitStatus
  databaseCommitStatus: OfficeDockingCommitStatus
  summary: string
  warnings: string[]
  error: string
  upload?: OfficeFileUploadResult
  outputFiles: OfficeEmployeeOutputFile[]
  sourceFile?: File
  templateResult?: Record<string, unknown>
  excelAnalysis?: Record<string, unknown>
  shipmentEtlPreview?: ShipmentEtlPreview
  fieldNames: string[]
  sampleRows: Record<string, unknown>[]
  rowCount: number
  textPreview: string
}

export interface UseChatOfficeDockingDeps {
  addAndSaveMessage: (content: string, role?: 'user' | 'ai' | 'task', extras?: Record<string, unknown>) => Promise<void>
  stageExcelAnalysisContext: (payload: Record<string, unknown>) => void
  sendDatabaseImportMessage: (message: string) => Promise<void>
  mode?: 'conversation' | 'review'
}

type OfficeDockingBatchPlan = {
  label: string
  templateItemIds: string[]
  databaseItemIds: string[]
}

const OFFICE_DOCKING_DECISION_OPTIONS: ChatDecisionOption[] = [
  {
    id: 'recommended',
    label: '按 AI 建议处理',
    description: '归档模板，并同步目标明确、可以安全执行的业务数据',
    message: '按建议处理',
    recommended: true,
  },
  {
    id: 'template-only',
    label: '仅归档模板库',
    description: '整理为对应行业模板，不写入任何业务数据库',
    message: '全部只归档到模板库',
  },
  {
    id: 'custom',
    label: '自定义处理方式',
    description: '继续告诉 AI 哪些归档、哪些入库，或先问清楚再决定',
    composePrefill: '我想这样处理：',
  },
]

const EMPLOYEE_LABELS: Record<string, string> = {
  [EXCEL_FULL_READ_EMPLOYEE_ID]: 'Excel 读取员',
  [CSV_FULL_READ_EMPLOYEE_ID]: 'CSV 全量读取员',
  [PDF_FULL_READ_EMPLOYEE_ID]: 'PDF 全量读取员',
  [PPT_FULL_READ_EMPLOYEE_ID]: 'PPT 全量读取员',
  [WORD_FULL_READ_EMPLOYEE_ID]: 'Word 全量读取员',
}

const KIND_LABELS: Record<string, string> = {
  [EXCEL_FULL_READ_EMPLOYEE_ID]: 'Excel',
  [CSV_FULL_READ_EMPLOYEE_ID]: 'CSV',
  [PDF_FULL_READ_EMPLOYEE_ID]: 'PDF',
  [PPT_FULL_READ_EMPLOYEE_ID]: 'PPT',
  [WORD_FULL_READ_EMPLOYEE_ID]: 'Word',
}

function newItemId(): string {
  return `office-docking-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

type DirectoryFile = File & { webkitRelativePath?: string }

function officeDockingRelativePath(file: File): string {
  return String((file as DirectoryFile).webkitRelativePath || file.name || '')
    .replace(/\\/g, '/')
    .replace(/^\/+/, '')
    .trim()
}

function isDirectorySystemFile(file: File): boolean {
  const segments = officeDockingRelativePath(file).split('/').filter(Boolean)
  return segments.some((segment) =>
    segment === '__MACOSX' || segment.startsWith('.') || segment.startsWith('~$'),
  )
}

function directoryRootLabel(files: File[]): string {
  const path = files.map(officeDockingRelativePath).find((value) => value.includes('/')) || ''
  return path.split('/')[0] || '所选文件夹'
}

function fileStem(fileName: string): string {
  const base = String(fileName || '').replace(/\\/g, '/').split('/').pop() || '办公文件'
  return base.replace(/\.[^.]+$/, '').trim() || '办公文件'
}

function applyTemplateRecommendation(item: ChatOfficeDockingReviewItem): void {
  const stem = fileStem(item.fileName)
  const recommendations: Record<OfficeDockingIntentId, { label: string; scope: string }> = {
    pending: { label: '办公文件模板', scope: '' },
    attendance_roster: { label: '考勤模板', scope: '' },
    attendance_source: { label: '考勤模板', scope: '' },
    shipment_delivery: { label: '发货单模板', scope: 'orders' },
    customer_product: { label: '客户产品模板', scope: 'products' },
    generic_table: { label: '通用表格模板', scope: '' },
    document: { label: '文档模板', scope: '' },
  }
  const recommendation = recommendations[item.intentId] || recommendations.pending
  item.templateTargetLabel = recommendation.label
  item.templateScope = recommendation.scope
  item.templateName = `${stem} · ${recommendation.label}`
}

function buildReviewAdviceMessage(item: ChatOfficeDockingReviewItem): string {
  const databaseAdvice = item.databaseAction
    ? `同步到「${item.databaseTargetLabel}」`
    : `暂不写业务数据库（${item.databaseDisabledReason || '没有识别到可靠的数据库目标'}）`
  return `[对接审核] 已阅读「${item.fileName}」，判断为“${item.intentLabel}”。建议归档为模板「${item.templateName}」，并${databaseAdvice}。请在审核区确认当前文件。`
}

function batchIntentSummary(items: ChatOfficeDockingReviewItem[]): string {
  const counts = new Map<string, number>()
  for (const item of items) counts.set(item.intentLabel, (counts.get(item.intentLabel) || 0) + 1)
  return [...counts.entries()].map(([label, count]) => `${label} ${count} 个`).join('、') || '未识别到可处理文件'
}

function isDirectDatabaseAction(item: ChatOfficeDockingReviewItem): boolean {
  return item.databaseAction === 'attendance_import' || item.databaseAction === 'shipment_etl_execute'
}

function buildBatchInsightMessage(
  items: ChatOfficeDockingReviewItem[],
  sourceLabel: string,
  skippedCount: number,
): string {
  const ready = items.filter((item) => item.status === 'ready')
  const failed = items.filter((item) => item.status === 'error')
  const directDatabase = ready.filter((item) => item.selectedDatabase && isDirectDatabaseAction(item))
  const mappingRequired = ready.filter((item) => item.databaseAction === 'customer_product_import')
  const details = items.map((item, index) => {
    if (item.status === 'error') return `${index + 1}. ${item.fileName}：读取失败（${item.error || '未知错误'}）`
    const target = directDatabase.includes(item)
      ? `可归档「${item.templateTargetLabel}」并同步「${item.databaseTargetLabel}」`
      : mappingRequired.includes(item)
        ? `建议先归档「${item.templateTargetLabel}」；客户/产品字段映射需另行核对`
        : `建议归档「${item.templateTargetLabel}」，暂不写业务库`
    return `${index + 1}. ${item.fileName}：${item.intentLabel}，${target}`
  })
  const skipped = skippedCount ? `；另忽略 ${skippedCount} 个系统或不支持的文件` : ''
  return [
    `我已经把${sourceLabel}全部读完了：成功 ${ready.length} 个，失败 ${failed.length} 个${skipped}。目前没有归档模板，也没有写入数据库。`,
    '',
    `整体判断：${batchIntentSummary(ready)}。`,
    '',
    '逐文件判断：',
    ...details,
    '',
    '我的建议：',
    `- 将 ${ready.length} 个读取成功的文件归档到各自对应的模板分类。`,
    `- 将其中 ${directDatabase.length} 个业务目标明确、具备确定性接口的文件同步到对应数据库。`,
    '- 读取失败或业务目标不明确的文件不写数据库。',
    ...(mappingRequired.length
      ? [`- ${mappingRequired.length} 个客户/产品业务表虽然找到了目标库，但字段映射还需要进一步核对，我不会把它们算作可直接写库。`]
      : []),
    '',
    '你想怎么处理这批文件？可以从下面选择，也可以继续在对话里问我或调整方案。',
  ].join('\n')
}

function outputRelpathFor(itemId: string, employeeId: string): string {
  if (employeeId === PDF_FULL_READ_EMPLOYEE_ID) return `outputs/chat-docking/${itemId}/document_full.txt`
  if (employeeId === WORD_FULL_READ_EMPLOYEE_ID) return `outputs/chat-docking/${itemId}/document_full.json`
  if (employeeId === PPT_FULL_READ_EMPLOYEE_ID) return `outputs/chat-docking/${itemId}/presentation_full.json`
  if (employeeId === CSV_FULL_READ_EMPLOYEE_ID) return `outputs/chat-docking/${itemId}/data.json`
  return `outputs/chat-docking/${itemId}/workbook.json`
}

function collectEmployeeOutputPaths(employeeData: Record<string, unknown>): string[] {
  const rows = [employeeData, ...asArray<Record<string, unknown>>(employeeData.items)]
  const keys = ['output_path', 'text_output_path', 'meta_output_path', 'images_index_path']
  const paths = new Set<string>()
  for (const row of rows) {
    for (const key of keys) {
      const value = asString(row[key]).trim()
      if (value) paths.add(value)
    }
  }
  return [...paths]
}

function firstJsonData(outputs: OfficeEmployeeOutputFile[]): Record<string, unknown> {
  const found = outputs.find((f) => f.kind === 'json' && f.json && typeof f.json === 'object')
  return asRecord(found?.json)
}

function firstText(outputs: OfficeEmployeeOutputFile[]): string {
  return asString(outputs.find((f) => f.kind === 'text' && f.text)?.text).trim()
}

function truncate(text: string, max = 6000): string {
  const raw = String(text || '').trim()
  return raw.length > max ? `${raw.slice(0, max)}\n...` : raw
}

function compactText(value: unknown): string {
  return String(value || '')
    .replace(/\s+/g, '')
    .trim()
}

function excelSheetNames(analysis?: Record<string, unknown>): string[] {
  const preview = asRecord(analysis?.preview_data)
  const fromPreview = asArray<unknown>(preview.sheet_names)
    .map((name) => asString(name).trim())
    .filter(Boolean)
  const fromSheets = asArray<Record<string, unknown>>(analysis?.sheets)
    .map((sheet) => asString(sheet.sheet_name || sheet.name).trim())
    .filter(Boolean)
  return [...new Set([...fromPreview, ...fromSheets])]
}

function allFieldNames(analysis?: Record<string, unknown>): string[] {
  const fields = extractFieldNames(analysis)
  const sheetFields = asArray<Record<string, unknown>>(analysis?.sheets).flatMap((sheet) =>
    asArray<unknown>(sheet.fields)
      .map((field) => {
        if (typeof field === 'string') return field.trim()
        const row = asRecord(field)
        return asString(row.label || row.name).trim()
      })
      .filter(Boolean),
  )
  return [...new Set([...fields, ...sheetFields])].slice(0, 80)
}

function inferOfficeDockingIntent(item: {
  fileName: string
  employeeId: string
  kindLabel: string
  excelAnalysis?: Record<string, unknown>
}): {
  intentId: OfficeDockingIntentId
  intentLabel: string
  intentSummary: string
  databaseTargetLabel: string
  databaseAction: OfficeDockingDatabaseAction
  databaseDisabledReason: string
  selectedDatabase: boolean
} {
  if (!item.excelAnalysis) {
    return {
      intentId: 'document',
      intentLabel: '普通办公文档',
      intentSummary: '已读取正文，建议归档为文档模板；未发现可安全写入业务库的表格结构',
      databaseTargetLabel: '',
      databaseAction: '',
      databaseDisabledReason: '该文件不是可入库表格',
      selectedDatabase: false,
    }
  }

  const sheets = excelSheetNames(item.excelAnalysis).map(compactText)
  const fields = allFieldNames(item.excelAnalysis).map(compactText)
  const file = compactText(item.fileName)
  const haystack = [...sheets, ...fields, file].join('|')
  const hasMingxi = sheets.includes('明细')
  const hasMonthly = sheets.includes('月度统计')
  const hasDingtalk = sheets.includes('每日统计') || sheets.includes('原始记录')
  const hasRosterFields = ['部门', '性质', '姓名'].filter((key) => haystack.includes(key)).length >= 2
  const hasProductFields =
    ['客户', '购买单位', '购货单位', '产品', '品名', '型号', '规格', '单价', '价格'].filter((key) => haystack.includes(key)).length >= 3
  const looksLikeDeliveryNote =
    (haystack.includes('送货单') || haystack.includes('发货单')) &&
    (haystack.includes('购货单位') || haystack.includes('购买单位') || haystack.includes('客户')) &&
    ['型号', '品名', '产品名称', '数量'].filter((key) => haystack.includes(key)).length >= 2

  if ((hasMingxi && (hasMonthly || hasRosterFields)) || file.includes('考勤转换结果')) {
    return {
      intentId: 'attendance_roster',
      intentLabel: '考勤转换结果/人员部门表',
      intentSummary: '识别到「明细/月度统计」结构，应写入太阳鸟考勤库，不走客户产品入库',
      databaseTargetLabel: '考勤库',
      databaseAction: 'attendance_import',
      databaseDisabledReason: '',
      selectedDatabase: true,
    }
  }

  if (hasDingtalk || file.includes('考勤')) {
    return {
      intentId: 'attendance_source',
      intentLabel: '钉钉考勤原始表',
      intentSummary: '识别到考勤统计结构，应写入太阳鸟考勤库',
      databaseTargetLabel: '考勤库',
      databaseAction: 'attendance_import',
      databaseDisabledReason: '',
      selectedDatabase: true,
    }
  }

  if (looksLikeDeliveryNote) {
    return {
      intentId: 'shipment_delivery',
      intentLabel: '送货单/发货单',
      intentSummary: '识别到送货单抬头与明细字段，确认后走送货单 ETL（客户+产品+发货单）',
      databaseTargetLabel: '客户/产品/发货单',
      databaseAction: 'shipment_etl_execute',
      databaseDisabledReason: '',
      selectedDatabase: true,
    }
  }

  if (hasProductFields) {
    return {
      intentId: 'customer_product',
      intentLabel: '客户/产品业务表',
      intentSummary: '识别到客户、产品、型号、价格等字段，可写入客户/产品库',
      databaseTargetLabel: '客户/产品库',
      databaseAction: 'customer_product_import',
      databaseDisabledReason: '',
      selectedDatabase: true,
    }
  }

  return {
    intentId: 'generic_table',
    intentLabel: '通用表格',
    intentSummary: '已读取表格，但业务目标不明确；建议先归档模板，避免误写数据库',
    databaseTargetLabel: '',
    databaseAction: '',
    databaseDisabledReason: '未识别到明确的业务库目标',
    selectedDatabase: false,
  }
}

function applyShipmentEtlIntent(item: ChatOfficeDockingReviewItem, preview: ShipmentEtlPreview): void {
  const notes = asArray<ShipmentEtlNotePreview>(preview.notes)
  const noteCount = Number(preview.note_count || notes.length) || notes.length
  const units = [...new Set(notes.map((n) => asString(n.unit_name).trim()).filter(Boolean))].slice(0, 3)
  const itemCount = notes.reduce((sum, n) => sum + (Number(n.item_count) || asArray(n.items).length || 0), 0)
  item.shipmentEtlPreview = {
    ...preview,
    notes,
    note_count: noteCount,
  }
  item.intentId = 'shipment_delivery'
  item.intentLabel = '送货单/发货单'
  item.intentSummary = asString(preview.message).trim() || `内容指纹识别到 ${noteCount} 张送货单，确认后写入客户、产品与发货单`
  item.databaseTargetLabel = '客户/产品/发货单'
  item.databaseAction = 'shipment_etl_execute'
  item.databaseDisabledReason = ''
  // 写库需用户确认勾选；重复导入时默认不勾
  const dup = Number(preview.duplicate_note_count || 0)
  item.selectedDatabase = dup < noteCount
  if (dup > 0) {
    item.warnings = [...item.warnings, `其中 ${dup} 张疑似已导入（幂等将跳过）`]
  }
  if (preview.ledger_risk) {
    item.warnings = [...item.warnings, `同文件另有约 ${Number(preview.ledger_available_count || 0)} 组历史流水未纳入本次导入`]
  }
  if (units.length) {
    item.fieldNames = [...new Set(['购货单位', '型号', '品名', '数量', ...item.fieldNames])].slice(0, 80)
  }
  if (!item.sampleRows.length && notes.length) {
    item.sampleRows = notes.slice(0, 5).map((note) => ({
      购货单位: asString(note.unit_name),
      工作表: asString(note.sheet_name),
      明细行: Number(note.item_count) || asArray(note.items).length || 0,
      金额: note.total_amount ?? '',
    }))
  }
  if (itemCount > 0) item.rowCount = Math.max(item.rowCount, itemCount)
}

async function previewShipmentExcelEtl(filePath: string, workspaceRoot?: string): Promise<ShipmentEtlPreview | null> {
  const path = asString(filePath).trim()
  if (!path) return null
  await primeCsrfCookie()
  const fd = new FormData()
  fd.append('file_path', path)
  if (workspaceRoot) fd.append('workspace_root', workspaceRoot)
  fd.append('include_ledger', 'auto')
  const res = await apiFetch('/api/excel/data/shipment-etl/preview', { method: 'POST', body: fd })
  const body = await res.json().catch(() => ({}))
  const data = asRecord(body)
  if (!res.ok || data.success === false) return null
  const notes = asArray<ShipmentEtlNotePreview>(data.notes)
  if (!notes.length) return null
  return { ...data, notes, note_count: Number(data.note_count || notes.length) || notes.length }
}

async function executeShipmentExcelEtl(item: ChatOfficeDockingReviewItem): Promise<Record<string, unknown>> {
  if (!item.upload?.file_path) throw new Error('缺少已上传文件路径')
  await primeCsrfCookie()
  const fd = new FormData()
  fd.append('file_path', item.upload.file_path)
  if (item.upload.workspace_root) fd.append('workspace_root', item.upload.workspace_root)
  fd.append('import_products', '1')
  fd.append('import_shipments', '1')
  fd.append('idempotent', '1')
  fd.append('include_ledger', '0')
  fd.append('confirm_ledger', '0')
  if (item.shipmentEtlPreview?.notes?.length) {
    fd.append('notes_json', JSON.stringify(item.shipmentEtlPreview.notes))
  }
  const res = await apiFetch('/api/excel/data/shipment-etl/execute', { method: 'POST', body: fd })
  const body = await res.json().catch(() => ({}))
  const data = asRecord(body)
  if (!res.ok || data.success === false) {
    throw new Error(String(data.message || data.error || `送货单 ETL 失败 HTTP ${res.status}`))
  }
  return data
}

function stringifyPreview(value: unknown, max = 6000): string {
  try {
    return truncate(JSON.stringify(value, null, 2), max)
  } catch {
    return truncate(String(value || ''), max)
  }
}

function rowsToGrid(columns: string[], rows: Record<string, unknown>[]): unknown[][] {
  return [columns, ...rows.slice(0, 20).map((row) => columns.map((col) => row[col] ?? ''))]
}

function buildCsvExcelAnalysis(upload: OfficeFileUploadResult, csvData: Record<string, unknown>, summary: string): Record<string, unknown> {
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

function buildWorkbookExcelAnalysis(
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

function extractFieldNames(analysis?: Record<string, unknown>): string[] {
  if (!analysis) return []
  return asArray<unknown>(analysis.fields)
    .map((field) => {
      if (typeof field === 'string') return field.trim()
      const row = asRecord(field)
      return asString(row.label || row.name).trim()
    })
    .filter(Boolean)
    .slice(0, 40)
}

function extractSampleRows(analysis?: Record<string, unknown>): Record<string, unknown>[] {
  const preview = asRecord(analysis?.preview_data)
  return asArray<Record<string, unknown>>(preview.sample_rows)
    .map((row) => asRecord(row))
    .slice(0, 8)
}

function buildPptText(jsonData: Record<string, unknown>): string {
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

async function archiveTemplateLibrary(item: ChatOfficeDockingReviewItem): Promise<Record<string, unknown>> {
  if (!item.sourceFile) throw new Error('缺少原始文件，无法归档模板')
  await primeCsrfCookie()
  const fd = new FormData()
  fd.append('file', item.sourceFile)
  fd.append('template_name', item.templateName || fileStem(item.fileName))
  if (item.templateScope) fd.append('template_scope', item.templateScope)
  fd.append('source', 'chat_office_docking_ai_advice')
  const res = await apiFetch('/api/templates/upload', {
    method: 'POST',
    body: fd,
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body?.success === false) {
    throw new Error(String(body?.message || body?.error || '模板库归档失败'))
  }
  return asRecord(body)
}

async function ingestAttendanceDatabase(item: ChatOfficeDockingReviewItem): Promise<Record<string, unknown>> {
  if (!item.upload?.file_path) throw new Error('缺少已上传文件路径')
  await primeCsrfCookie()
  const res = await apiFetch('/api/mod/taiyangniao-pro/attendance/import-workbook', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      file_path: item.upload.file_path,
      workspace_root: item.upload.workspace_root,
      source_name: item.fileName,
      sync_ui_tables: true,
    }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body?.success === false) {
    throw new Error(String(body?.error || body?.message || `考勤入库失败 HTTP ${res.status}`))
  }
  return asRecord(body?.data || body)
}

export function useChatOfficeDocking(deps: UseChatOfficeDockingDeps) {
  const mode = deps.mode || 'review'
  const officeDockingInputRef = ref<HTMLInputElement | null>(null)
  const officeDockingFolderInputRef = ref<HTMLInputElement | null>(null)
  const officeDockingProcessing = ref(false)
  const officeDockingPanelOpen = ref(false)
  const officeDockingReviewItems = ref<ChatOfficeDockingReviewItem[]>([])
  const officeDockingAwaitingDecision = ref(false)
  const officeDockingBatchPlan = ref<OfficeDockingBatchPlan | null>(null)
  const officeDockingPendingCount = computed(() => officeDockingReviewItems.value.filter(
    (item) => item.status === 'ready' && item.commitStatus !== 'committed' && item.commitStatus !== 'skipped',
  ).length)

  function triggerOfficeDocking() {
    if (officeDockingProcessing.value) return
    officeDockingInputRef.value?.click()
  }

  function triggerOfficeDockingFolder() {
    if (officeDockingProcessing.value) return
    officeDockingFolderInputRef.value?.click()
  }

  function touchItems() {
    officeDockingReviewItems.value = [...officeDockingReviewItems.value]
  }

  async function analyzeFile(file: File, displayName = file.name): Promise<void> {
    const employeeId = resolveOfficeReadEmployeeForFile(file.name)
    const item: ChatOfficeDockingReviewItem = {
      id: newItemId(),
      fileName: displayName,
      employeeId,
      employeeLabel: EMPLOYEE_LABELS[employeeId] || employeeId || '办公员工',
      kindLabel: KIND_LABELS[employeeId] || '办公文件',
      status: 'running',
      commitStatus: '',
      intentId: 'pending',
      intentLabel: '待识别',
      intentSummary: '正在读取文件内容并判断业务用途',
      databaseTargetLabel: '',
      databaseAction: '',
      databaseDisabledReason: '',
      selectedTemplate: true,
      selectedDatabase: false,
      templateName: `${fileStem(displayName)} · 办公文件模板`,
      templateScope: '',
      templateTargetLabel: '办公文件模板',
      templateCommitStatus: '',
      databaseCommitStatus: '',
      summary: '正在调用办公员工识别...',
      warnings: [],
      error: '',
      outputFiles: [],
      sourceFile: file,
      fieldNames: [],
      sampleRows: [],
      rowCount: 0,
      textPreview: '',
    }
    officeDockingReviewItems.value.push(item)
    touchItems()

    if (!employeeId || !isOfficeDockingFileSupported(file.name)) {
      item.status = 'error'
      item.summary = ''
      item.error = '该文件类型未匹配到办公读取员工'
      touchItems()
      return
    }

    try {
      const upload = await uploadChatOfficeFile(file)
      item.upload = upload
      item.summary = `已上传，正在由 ${item.employeeLabel} 读取...`
      touchItems()
      const employeeData = await runOfficeEmployeeRead(employeeId, upload.file_path, upload.workspace_root, {
        outputRelpath: outputRelpathFor(item.id, employeeId),
      })
      const warnings = [
        ...asArray<unknown>(employeeData.warnings)
          .map((w) => asString(w))
          .filter(Boolean),
        ...asArray<Record<string, unknown>>(employeeData.items)
          .flatMap((row) => asArray<unknown>(row.warnings).map((w) => asString(w)))
          .filter(Boolean),
      ]
      item.warnings = warnings
      const outputs = await readOfficeEmployeeOutputs(upload.workspace_root, collectEmployeeOutputPaths(employeeData))
      item.outputFiles = outputs
      const jsonData = firstJsonData(outputs)
      const textData = firstText(outputs)
      const rawSummary = asString(employeeData.summary).trim()
      item.summary = rawSummary || `${item.employeeLabel} 已完成识别`

      if (employeeId === EXCEL_FULL_READ_EMPLOYEE_ID) {
        item.excelAnalysis = buildWorkbookExcelAnalysis(upload, jsonData, item.summary)
      } else if (employeeId === CSV_FULL_READ_EMPLOYEE_ID) {
        item.excelAnalysis = buildCsvExcelAnalysis(upload, jsonData, item.summary)
      }

      if (employeeId === PPT_FULL_READ_EMPLOYEE_ID) {
        item.textPreview = buildPptText(jsonData)
      } else if (textData) {
        item.textPreview = truncate(textData, 12_000)
      } else if (Object.keys(jsonData).length) {
        item.textPreview = stringifyPreview(jsonData, 12_000)
      }

      item.fieldNames = extractFieldNames(item.excelAnalysis)
      item.sampleRows = extractSampleRows(item.excelAnalysis)
      item.rowCount = item.sampleRows.length
      if (employeeId === CSV_FULL_READ_EMPLOYEE_ID) {
        item.rowCount = Number(jsonData.row_count || item.sampleRows.length) || item.sampleRows.length
      } else if (employeeId === EXCEL_FULL_READ_EMPLOYEE_ID) {
        const sheets = asArray<Record<string, unknown>>(jsonData.sheets)
        item.rowCount = sheets.reduce((sum, sheet) => sum + (Number(sheet.row_count) || 0), 0)
      }
      const intent = inferOfficeDockingIntent(item)
      item.intentId = intent.intentId
      item.intentLabel = intent.intentLabel
      item.intentSummary = intent.intentSummary
      item.databaseTargetLabel = intent.databaseTargetLabel
      item.databaseAction = intent.databaseAction
      item.databaseDisabledReason = intent.databaseDisabledReason
      item.selectedDatabase = intent.selectedDatabase

      const canRunShipmentEtl =
        Boolean(item.upload?.file_path) &&
        item.excelAnalysis &&
        item.intentId !== 'attendance_roster' &&
        item.intentId !== 'attendance_source' &&
        (employeeId === EXCEL_FULL_READ_EMPLOYEE_ID || employeeId === CSV_FULL_READ_EMPLOYEE_ID)
      if (canRunShipmentEtl) {
        try {
          const shipmentPreview = await previewShipmentExcelEtl(item.upload!.file_path, item.upload!.workspace_root)
          if (shipmentPreview) applyShipmentEtlIntent(item, shipmentPreview)
        } catch {
          // 预览失败不阻断办公对接；仍保留字段启发式意图
        }
      }

      applyTemplateRecommendation(item)
      item.status = 'ready'
      const shipmentNoteCount = Number(item.shipmentEtlPreview?.note_count || 0)
      item.summary = shipmentNoteCount
        ? `${item.employeeLabel} 已识别 ${item.fileName}：送货单 ${shipmentNoteCount} 张；意图：${item.intentLabel}`
        : `${item.employeeLabel} 已识别 ${item.fileName}${item.fieldNames.length ? `，字段 ${item.fieldNames.length} 个` : ''}${item.rowCount ? `，行 ${item.rowCount} 条` : ''}；意图：${item.intentLabel}`
    } catch (err) {
      item.status = 'error'
      item.error = err instanceof Error ? err.message : String(err || '识别失败')
      item.summary = ''
    } finally {
      touchItems()
    }
  }

  async function onOfficeDockingFileChange(event: Event) {
    const input = event.target as HTMLInputElement | null
    const selectedFiles = Array.from(input?.files || [])
    const isDirectorySelection = Boolean(
      input?.hasAttribute('webkitdirectory') || selectedFiles.some((file) => officeDockingRelativePath(file).includes('/')),
    )
    const folderLabel = directoryRootLabel(selectedFiles)
    const files = isDirectorySelection
      ? selectedFiles.filter((file) => !isDirectorySystemFile(file) && isOfficeDockingFileSupported(file.name))
      : selectedFiles
    const skippedCount = selectedFiles.length - files.length
    if (input) input.value = ''
    if (!selectedFiles.length) return
    if (!files.length) {
      await deps.addAndSaveMessage(`[对接] 文件夹「${folderLabel}」中没有可识别的办公文件。`, 'ai')
      return
    }
    officeDockingPanelOpen.value = mode === 'review'
    officeDockingProcessing.value = true
    officeDockingReviewItems.value = []
    officeDockingAwaitingDecision.value = false
    officeDockingBatchPlan.value = null
    const skippedText = skippedCount ? `，已忽略 ${skippedCount} 个系统或不支持的文件` : ''
    const sourceText = isDirectorySelection ? `文件夹「${folderLabel}」中的 ` : ''
    await deps.addAndSaveMessage(
      mode === 'conversation'
        ? `[对接] 已收到${sourceText}${files.length} 个可识别文件${skippedText}。我会先把这一批全部读完，再一次和你商量怎么处理；读取阶段不会归档模板或写入数据库。`
        : `[对接] 已收到${sourceText}${files.length} 个可识别文件${skippedText}，开始调用办公员工识别。`,
      'ai',
    )
    try {
      for (const file of files) {
        await analyzeFile(file, isDirectorySelection ? officeDockingRelativePath(file) : file.name)
      }
    } finally {
      officeDockingProcessing.value = false
    }
    if (mode === 'conversation') {
      officeDockingAwaitingDecision.value = officeDockingReviewItems.value.some((item) => item.status === 'ready')
      const sourceLabel = isDirectorySelection ? `文件夹「${folderLabel}」里的文件` : '这批文件'
      await deps.addAndSaveMessage(
        buildBatchInsightMessage(officeDockingReviewItems.value, sourceLabel, skippedCount),
        'ai',
        { decisionOptions: OFFICE_DOCKING_DECISION_OPTIONS },
      )
      return
    }
    const firstReady = officeDockingReviewItems.value.find((item) => item.status === 'ready' && !item.commitStatus)
    if (firstReady) await deps.addAndSaveMessage(buildReviewAdviceMessage(firstReady), 'ai')
  }

  function toggleOfficeDockingTarget(id: string, target: OfficeDockingTarget, enabled: boolean) {
    const item = officeDockingReviewItems.value.find((row) => row.id === id)
    if (!item) return
    if (target === 'template') item.selectedTemplate = enabled
    if (target === 'database' && item.excelAnalysis && item.databaseAction) {
      item.selectedDatabase = enabled
    }
    touchItems()
  }

  function updateOfficeDockingTemplateName(id: string, value: string) {
    const item = officeDockingReviewItems.value.find((row) => row.id === id)
    if (!item || item.commitStatus === 'committing') return
    item.templateName = String(value || '').trimStart()
    touchItems()
  }

  function currentReviewItem(): ChatOfficeDockingReviewItem | undefined {
    return officeDockingReviewItems.value.find(
      (item) => item.commitStatus !== 'committed' && item.commitStatus !== 'skipped',
    )
  }

  async function announceNextAdvice(): Promise<void> {
    const next = currentReviewItem()
    if (next?.status === 'ready') await deps.addAndSaveMessage(buildReviewAdviceMessage(next), 'ai')
    if (!next && officeDockingReviewItems.value.length) {
      await deps.addAndSaveMessage('[对接] 本批文件审核完成。', 'ai')
    }
  }

  async function executeOfficeDockingItem(item: ChatOfficeDockingReviewItem): Promise<void> {
    item.commitStatus = 'committing'
    item.error = ''
    touchItems()
    try {
      if (item.selectedTemplate && item.templateCommitStatus !== 'committed') {
        item.templateCommitStatus = 'committing'
        touchItems()
        try {
          item.templateResult = await archiveTemplateLibrary(item)
          item.templateCommitStatus = 'committed'
        } catch (error) {
          item.templateCommitStatus = 'failed'
          throw error
        }
      }
      if (item.selectedDatabase && item.databaseCommitStatus !== 'committed') {
        item.databaseCommitStatus = 'committing'
        touchItems()
        try {
          if (!item.excelAnalysis) {
            throw new Error('该文件没有可导入数据库的表格上下文')
          }
          if (item.databaseAction === 'attendance_import') {
            const result = await ingestAttendanceDatabase(item)
            const employeeRows = Number(result.employee_rows || 0)
            const departmentRows = Number(result.department_rows || 0)
            item.summary = `考勤入库完成：人员 ${employeeRows} 条，部门 ${departmentRows} 条`
          } else if (item.databaseAction === 'shipment_etl_execute') {
            const result = await executeShipmentExcelEtl(item)
            const noteCount = Number(result.note_count || item.shipmentEtlPreview?.note_count || 0)
            const shipmentCreated = Number(result.shipment_created || 0)
            const productImported = Number(asRecord(result.product_result).imported || 0)
            item.summary = `送货单 ETL 完成：单 ${noteCount || shipmentCreated} 张，发货单新建 ${shipmentCreated}，产品写入 ${productImported}`
          } else if (item.databaseAction === 'customer_product_import') {
            deps.stageExcelAnalysisContext(item.excelAnalysis)
            await deps.sendDatabaseImportMessage(`导入数据库，确认导入：${item.fileName}`)
          } else {
            throw new Error(item.databaseDisabledReason || '未识别到可写入的业务数据库')
          }
          item.databaseCommitStatus = 'committed'
        } catch (error) {
          item.databaseCommitStatus = 'failed'
          throw error
        }
      }
      item.commitStatus = 'committed'
    } catch (err) {
      item.commitStatus = 'failed'
      item.error = err instanceof Error ? err.message : String(err || '提交失败')
    } finally {
      touchItems()
    }
  }

  async function confirmOfficeDockingReview() {
    const item = currentReviewItem()
    if (
      !item ||
      item.status !== 'ready' ||
      item.commitStatus === 'committing' ||
      (!item.selectedTemplate && !item.selectedDatabase)
    ) return
    await executeOfficeDockingItem(item)
    if (item.commitStatus === 'failed') {
      await deps.addAndSaveMessage(`[对接] 「${item.fileName}」处理失败：${item.error}。请调整后重试或跳过。`, 'ai')
      return
    }
    const targets = [item.selectedTemplate ? '模板库' : '', item.selectedDatabase ? item.databaseTargetLabel : ''].filter(Boolean)
    await deps.addAndSaveMessage(`[对接] 「${item.fileName}」已处理到 ${targets.join('、')}。`, 'ai')
    await announceNextAdvice()
  }

  function readyBatchItems(): ChatOfficeDockingReviewItem[] {
    return officeDockingReviewItems.value.filter((item) => item.status === 'ready')
  }

  function recommendedDatabaseItems(items: ChatOfficeDockingReviewItem[]): ChatOfficeDockingReviewItem[] {
    return items.filter((item) => item.selectedDatabase && isDirectDatabaseAction(item))
  }

  function makeBatchPlan(label: string, templateItems: ChatOfficeDockingReviewItem[], databaseItems: ChatOfficeDockingReviewItem[]): OfficeDockingBatchPlan {
    return {
      label,
      templateItemIds: templateItems.map((item) => item.id),
      databaseItemIds: databaseItems.map((item) => item.id),
    }
  }

  function resolveConversationPlan(message: string): OfficeDockingBatchPlan | 'cancel' | null {
    const normalized = String(message || '').replace(/\s+/g, '')
    const items = readyBatchItems()
    if (!normalized || !items.length) return null
    if (/^(先不处理|暂不处理|取消这批|不要处理|先放着|全部跳过)[。！!]*$/.test(normalized)) return 'cancel'
    if (/^(按建议处理|就按(这个|你的|AI的)?建议处理?|照你的建议处理?|按你说的(方案)?处理?|都按你说的办)[。！!]*$/.test(normalized)) {
      return makeBatchPlan('按 AI 建议处理', items, recommendedDatabaseItems(items))
    }
    if (
      /(全部|所有|这批).*(只归档|仅归档|只放|只存).*(模板|模版)/.test(normalized) ||
      /(全部|所有|这批).*(模板|模版).*(不入库|不写库|不写数据库)/.test(normalized) ||
      !/[吗么？?]|能否|可以不/.test(normalized) &&
        /(全部|所有|这批|都|统一).*(归档|保存|存到|放到|收进).*(模板|模版)/.test(normalized) &&
        !/(入库|同步|写入).*(数据库|业务库|对应库)/.test(normalized)
    ) {
      return makeBatchPlan('全部只归档到模板库', items, [])
    }
    if (/(发货单|送货单).*(入库|同步).*(其余|其他).*(归档|模板|模版)/.test(normalized)) {
      const shipments = items.filter((item) => item.intentId === 'shipment_delivery' && isDirectDatabaseAction(item))
      return makeBatchPlan('发货单入库，其余归档', items, shipments)
    }
    if (/(考勤).*(入库|同步).*(其余|其他).*(归档|模板|模版)/.test(normalized)) {
      const attendance = items.filter(
        (item) => (item.intentId === 'attendance_roster' || item.intentId === 'attendance_source') && isDirectDatabaseAction(item),
      )
      return makeBatchPlan('考勤表入库，其余归档', items, attendance)
    }
    if (/(全部|所有|这批).*(入库|同步|写入).*(数据库|业务库|对应库)/.test(normalized)) {
      return makeBatchPlan('全部归档，并将可确定执行的文件写入对应库', items, recommendedDatabaseItems(items))
    }
    return null
  }

  function batchPlanDescription(plan: OfficeDockingBatchPlan): string {
    const databaseTargets = new Map<string, number>()
    for (const item of readyBatchItems()) {
      if (!plan.databaseItemIds.includes(item.id)) continue
      const label = item.databaseTargetLabel || '对应数据库'
      databaseTargets.set(label, (databaseTargets.get(label) || 0) + 1)
    }
    const databaseText = plan.databaseItemIds.length
      ? [...databaseTargets.entries()].map(([label, count]) => `${label} ${count} 个`).join('、')
      : '不写数据库'
    return `模板库 ${plan.templateItemIds.length} 个；${databaseText}`
  }

  async function executeBatchPlan(plan: OfficeDockingBatchPlan): Promise<void> {
    const items = readyBatchItems()
    for (const item of items) {
      item.selectedTemplate = plan.templateItemIds.includes(item.id)
      item.selectedDatabase = plan.databaseItemIds.includes(item.id)
      if (!item.selectedTemplate && !item.selectedDatabase) {
        item.commitStatus = 'skipped'
        continue
      }
      await executeOfficeDockingItem(item)
    }
    touchItems()
  }

  async function handleOfficeDockingConversationDecision(message: string): Promise<boolean> {
    if (mode !== 'conversation' || !officeDockingAwaitingDecision.value) return false
    const normalized = String(message || '').replace(/\s+/g, '')
    if (/^确认执行[。！!]*$/.test(normalized)) {
      await deps.addAndSaveMessage(message, 'user')
      const plan = officeDockingBatchPlan.value
      if (!plan) {
        await deps.addAndSaveMessage('还没有形成明确的整批处理方案。请先告诉我想怎么处理，例如“按建议处理”或“全部只归档到模板库”。', 'ai')
        return true
      }
      await deps.addAndSaveMessage(`收到，开始执行“${plan.label}”。`, 'ai')
      await executeBatchPlan(plan)
      const committed = officeDockingReviewItems.value.filter((item) => item.commitStatus === 'committed')
      const failed = officeDockingReviewItems.value.filter((item) => item.commitStatus === 'failed')
      const skipped = officeDockingReviewItems.value.filter((item) => item.commitStatus === 'skipped')
      officeDockingAwaitingDecision.value = failed.length > 0
      officeDockingBatchPlan.value = null
      const failureText = failed.length ? `；失败 ${failed.length} 个：${failed.map((item) => item.fileName).join('、')}` : ''
      await deps.addAndSaveMessage(
        `这批文件执行完成：成功 ${committed.length} 个，未处理 ${skipped.length} 个${failureText}。${failed.length ? '失败项没有被标记为成功，可以调整后重新安排。' : ''}`,
        'ai',
      )
      return true
    }

    const plan = resolveConversationPlan(message)
    if (!plan) return false
    await deps.addAndSaveMessage(message, 'user')
    if (plan === 'cancel') {
      for (const item of readyBatchItems()) item.commitStatus = 'skipped'
      touchItems()
      officeDockingAwaitingDecision.value = false
      officeDockingBatchPlan.value = null
      await deps.addAndSaveMessage('好的，这批文件先不处理。没有归档模板，也没有写入数据库。以后需要时可以重新上传或继续告诉我处理方案。', 'ai')
      return true
    }
    officeDockingBatchPlan.value = plan
    await deps.addAndSaveMessage(
      `我理解的整批方案是“${plan.label}”：${batchPlanDescription(plan)}。现在还没有执行；如果理解正确，请回复“确认执行”。要调整的话，直接用自然语言告诉我。`,
      'ai',
    )
    return true
  }

  async function skipCurrentOfficeDockingReview() {
    const item = currentReviewItem()
    if (!item || item.commitStatus === 'committing') return
    item.commitStatus = 'skipped'
    touchItems()
    await deps.addAndSaveMessage(`[对接] 已跳过「${item.fileName}」，没有执行新的归档或数据库写入。`, 'ai')
    await announceNextAdvice()
  }

  function clearOfficeDockingReview() {
    officeDockingPanelOpen.value = false
    officeDockingReviewItems.value = []
    officeDockingAwaitingDecision.value = false
    officeDockingBatchPlan.value = null
  }

  return {
    officeDockingInputRef,
    officeDockingFolderInputRef,
    officeDockingProcessing,
    officeDockingPanelOpen,
    officeDockingReviewItems,
    officeDockingPendingCount,
    officeDockingAwaitingDecision,
    triggerOfficeDocking,
    triggerOfficeDockingFolder,
    onOfficeDockingFileChange,
    toggleOfficeDockingTarget,
    updateOfficeDockingTemplateName,
    confirmOfficeDockingReview,
    skipCurrentOfficeDockingReview,
    handleOfficeDockingConversationDecision,
    clearOfficeDockingReview,
  }
}

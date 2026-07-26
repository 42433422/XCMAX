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
import { etlApi } from '@/api/etl'

type OfficeDockingTarget = 'knowledge' | 'database'
type OfficeDockingStatus = 'running' | 'ready' | 'error'
type OfficeDockingCommitStatus = '' | 'committing' | 'committed' | 'failed'
type OfficeDockingIntentId =
  | 'pending'
  | 'attendance_roster'
  | 'attendance_source'
  | 'shipment_delivery'
  | 'customer_product'
  | 'generic_table'
  | 'document'
type OfficeDockingDatabaseAction =
  | ''
  | 'attendance_import'
  | 'shipment_etl_execute'
  | 'customer_product_import'

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
  selectedKnowledge: boolean
  selectedDatabase: boolean
  summary: string
  warnings: string[]
  error: string
  upload?: OfficeFileUploadResult
  etlUploadId?: string
  sourceFile?: File
  outputFiles: OfficeEmployeeOutputFile[]
  knowledgeText: string
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
  openEtlCenter: (runIds: string[]) => Promise<void> | void
}

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
  return String(value || '').replace(/\s+/g, '').trim()
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
      intentSummary: '适合先进入知识库，未发现可结构化写库的表格上下文',
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
  const hasProductFields = ['客户', '购买单位', '购货单位', '产品', '品名', '型号', '规格', '单价', '价格']
    .filter((key) => haystack.includes(key)).length >= 3
  const looksLikeDeliveryNote = (
    (haystack.includes('送货单') || haystack.includes('发货单'))
    && (haystack.includes('购货单位') || haystack.includes('购买单位') || haystack.includes('客户'))
    && ['型号', '品名', '产品名称', '数量'].filter((key) => haystack.includes(key)).length >= 2
  )

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
    intentSummary: '已读取表格，但业务目标不明确；先进入知识库，避免误写数据库',
    databaseTargetLabel: '',
    databaseAction: '',
    databaseDisabledReason: '未识别到明确的业务库目标',
    selectedDatabase: false,
  }
}

function applyShipmentEtlIntent(
  item: ChatOfficeDockingReviewItem,
  preview: ShipmentEtlPreview,
): void {
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
  item.intentSummary = asString(preview.message).trim()
    || `内容指纹识别到 ${noteCount} 张送货单，确认后写入客户、产品与发货单`
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
    item.warnings = [
      ...item.warnings,
      `同文件另有约 ${Number(preview.ledger_available_count || 0)} 组历史流水未纳入本次导入`,
    ]
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

async function previewShipmentExcelEtl(
  filePath: string,
  workspaceRoot?: string,
): Promise<ShipmentEtlPreview | null> {
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

function stringifyPreview(value: unknown, max = 6000): string {
  try {
    return truncate(JSON.stringify(value, null, 2), max)
  } catch {
    return truncate(String(value || ''), max)
  }
}

function rowsToGrid(columns: string[], rows: Record<string, unknown>[]): unknown[][] {
  return [
    columns,
    ...rows.slice(0, 20).map((row) => columns.map((col) => row[col] ?? '')),
  ]
}

function buildCsvExcelAnalysis(
  upload: OfficeFileUploadResult,
  csvData: Record<string, unknown>,
  summary: string,
): Record<string, unknown> {
  const columns = asArray<unknown>(csvData.columns).map((c) => asString(c).trim()).filter(Boolean)
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
  return asArray<Record<string, unknown>>(preview.sample_rows).map((row) => asRecord(row)).slice(0, 8)
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

function buildKnowledgeText(item: {
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

export function useChatOfficeDocking(deps: UseChatOfficeDockingDeps) {
  const officeDockingInputRef = ref<HTMLInputElement | null>(null)
  const officeDockingProcessing = ref(false)
  const officeDockingPanelOpen = ref(false)
  const officeDockingReviewItems = ref<ChatOfficeDockingReviewItem[]>([])
  const officeDockingPendingCount = computed(
    () => officeDockingReviewItems.value.filter((item) => item.status === 'ready').length,
  )

  function triggerOfficeDocking() {
    if (officeDockingProcessing.value) return
    officeDockingInputRef.value?.click()
  }

  function touchItems() {
    officeDockingReviewItems.value = [...officeDockingReviewItems.value]
  }

  async function analyzeFile(file: File): Promise<void> {
    const employeeId = resolveOfficeReadEmployeeForFile(file.name)
    const item: ChatOfficeDockingReviewItem = {
      id: newItemId(),
      fileName: file.name,
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
      selectedKnowledge: true,
      selectedDatabase: false,
      summary: '正在调用办公员工识别...',
      warnings: [],
      error: '',
      outputFiles: [],
      knowledgeText: '',
      fieldNames: [],
      sampleRows: [],
      rowCount: 0,
      textPreview: '',
      sourceFile: file,
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
      const etlUploadPromise = etlApi.upload(file).catch((error) => {
        item.warnings = [
          ...item.warnings,
          `数据对接中心上传暂不可用：${error instanceof Error ? error.message : '上传失败'}`,
        ]
        return null
      })
      const upload = await uploadChatOfficeFile(file)
      item.upload = upload
      const etlUpload = await etlUploadPromise
      item.etlUploadId = etlUpload?.upload_id
      item.summary = `已上传，正在由 ${item.employeeLabel} 读取...`
      touchItems()
      const employeeData = await runOfficeEmployeeRead(
        employeeId,
        upload.file_path,
        upload.workspace_root,
        { outputRelpath: outputRelpathFor(item.id, employeeId) },
      )
      const warnings = [
        ...asArray<unknown>(employeeData.warnings).map((w) => asString(w)).filter(Boolean),
        ...asArray<Record<string, unknown>>(employeeData.items)
          .flatMap((row) => asArray<unknown>(row.warnings).map((w) => asString(w)))
          .filter(Boolean),
      ]
      item.warnings = warnings
      const outputs = await readOfficeEmployeeOutputs(
        upload.workspace_root,
        collectEmployeeOutputPaths(employeeData),
      )
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

      const canRunShipmentEtl = (
        Boolean(item.upload?.file_path)
        && item.excelAnalysis
        && item.intentId !== 'attendance_roster'
        && item.intentId !== 'attendance_source'
        && (employeeId === EXCEL_FULL_READ_EMPLOYEE_ID || employeeId === CSV_FULL_READ_EMPLOYEE_ID)
      )
      if (canRunShipmentEtl) {
        try {
          const shipmentPreview = await previewShipmentExcelEtl(
            item.upload!.file_path,
            item.upload!.workspace_root,
          )
          if (shipmentPreview) applyShipmentEtlIntent(item, shipmentPreview)
        } catch {
          // 预览失败不阻断办公对接；仍保留字段启发式意图
        }
      }

      item.knowledgeText = buildKnowledgeText(item)
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
    const files = Array.from(input?.files || [])
    if (input) input.value = ''
    if (!files.length) return
    officeDockingPanelOpen.value = true
    officeDockingProcessing.value = true
    officeDockingReviewItems.value = []
    await deps.addAndSaveMessage(
      `[对接] 已收到 ${files.length} 个文件，开始调用办公员工识别。`,
      'ai',
    )
    try {
      for (const file of files) {
        await analyzeFile(file)
      }
    } finally {
      officeDockingProcessing.value = false
    }
  }

  function toggleOfficeDockingTarget(id: string, target: OfficeDockingTarget, enabled: boolean) {
    const item = officeDockingReviewItems.value.find((row) => row.id === id)
    if (!item) return
    if (target === 'knowledge') item.selectedKnowledge = enabled
    if (target === 'database' && item.excelAnalysis && item.databaseAction) {
      item.selectedDatabase = enabled
    }
    touchItems()
  }

  async function confirmOfficeDockingReview() {
    const ready = officeDockingReviewItems.value.filter((item) => (
      item.status === 'ready'
      && item.commitStatus !== 'committed'
      && item.commitStatus !== 'committing'
      && (item.selectedKnowledge || item.selectedDatabase)
    ))
    if (!ready.length) return
    for (const item of ready) {
      item.commitStatus = 'committing'
      touchItems()
      try {
        if (!item.etlUploadId && item.sourceFile) {
          const upload = await etlApi.upload(item.sourceFile)
          item.etlUploadId = upload.upload_id
        }
        if (!item.etlUploadId) throw new Error('文件尚未进入数据对接中心')

        const targets: string[] = []
        if (item.selectedKnowledge) targets.push('knowledge')
        if (item.selectedDatabase) {
          if (item.databaseAction === 'attendance_import') targets.push('attendance')
          else if (item.databaseAction === 'shipment_etl_execute') {
            targets.push('customers', 'products', 'shipment_records')
          } else if (item.databaseAction === 'customer_product_import') {
            targets.push('customers', 'products')
          } else {
            throw new Error(item.databaseDisabledReason || '未识别到业务目标')
          }
        }
        const runs = []
        for (const targetType of [...new Set(targets)]) {
          runs.push(await etlApi.preview({
            upload_id: item.etlUploadId,
            target_type: targetType,
          }))
        }
        if (!runs.length) throw new Error('请选择至少一个对接目标')
        item.summary = `已创建 ${runs.length} 个预演任务，等待在数据对接中心确认`
        item.commitStatus = 'committed'
        await deps.openEtlCenter(runs.map((run) => run.id))
      } catch (err) {
        item.commitStatus = 'failed'
        item.error = err instanceof Error ? err.message : String(err || '提交失败')
      } finally {
        touchItems()
      }
    }
    const okCount = ready.filter((item) => item.commitStatus === 'committed').length
    const failCount = ready.filter((item) => item.commitStatus === 'failed').length
    await deps.addAndSaveMessage(
      `[对接] 已创建预演任务：成功 ${okCount} 个${failCount ? `，失败 ${failCount} 个` : ''}。数据不会在此处直接写库。`,
      failCount ? 'ai' : 'ai',
    )
  }

  function clearOfficeDockingReview() {
    officeDockingPanelOpen.value = false
    officeDockingReviewItems.value = []
  }

  return {
    officeDockingInputRef,
    officeDockingProcessing,
    officeDockingPanelOpen,
    officeDockingReviewItems,
    officeDockingPendingCount,
    triggerOfficeDocking,
    onOfficeDockingFileChange,
    toggleOfficeDockingTarget,
    confirmOfficeDockingReview,
    clearOfficeDockingReview,
  }
}

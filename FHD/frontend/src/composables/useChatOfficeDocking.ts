import { computed, getCurrentScope, onScopeDispose, ref } from 'vue'
import { primeCsrfCookie } from '@/api/core'
import { etlApi, type EtlRun } from '@/api/etl'
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

type OfficeDockingTarget = 'template' | 'database' | 'knowledge'
type OfficeDockingStatus = 'running' | 'ready' | 'error'
type OfficeDockingCommitStatus = '' | 'committing' | 'committed' | 'partial' | 'failed' | 'rolled_back' | 'skipped'
type OfficeDockingIntentId =
  | 'pending'
  | 'attendance_roster'
  | 'attendance_source'
  | 'shipment_delivery'
  | 'customer_product'
  | 'generic_table'
  | 'document'
type OfficeDockingDatabaseAction = '' | 'attendance_import' | 'shipment_etl_execute' | 'customer_product_import' | 'universal_etl_execute'

export type OfficeDockingProgressPhase = 'idle' | 'inventory' | 'reading' | 'reasoning' | 'planning' | 'stopping' | 'completed' | 'cancelled'

export type OfficeDockingIgnoredFile = {
  fileName: string
  reason: string
}

export type ChatOfficeDockingProgress = {
  phase: OfficeDockingProgressPhase
  sourceLabel: string
  total: number
  completed: number
  currentIndex: number
  currentFile: string
  success: number
  failed: number
  failures: Array<{ fileName: string; reason: string }>
  ignored: OfficeDockingIgnoredFile[]
  elapsedSeconds: number
  percent: number
}

export type ShipmentEtlNotePreview = {
  sheet_name?: string
  unit_name?: string
  profile_id?: string
  profile_target?: string
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
  selectedKnowledge?: boolean
  templateName: string
  templateScope: string
  templateTargetLabel: string
  templateCommitStatus: OfficeDockingCommitStatus
  databaseCommitStatus: OfficeDockingCommitStatus
  knowledgeCommitStatus?: OfficeDockingCommitStatus
  summary: string
  warnings: string[]
  error: string
  templateError?: string
  databaseError?: string
  knowledgeError?: string
  rollbackError?: string
  upload?: OfficeFileUploadResult
  outputFiles: OfficeEmployeeOutputFile[]
  sourceFile?: File
  templateResult?: Record<string, unknown>
  excelAnalysis?: Record<string, unknown>
  shipmentEtlPreview?: ShipmentEtlPreview
  databaseRun?: EtlRun
  databaseRuns?: EtlRun[]
  knowledgeRun?: EtlRun
  etlUpload?: {
    upload_id: string
    file_name: string
    sha256: string
    relative_path?: string
  }
  templateCandidates?: Array<{ name: string; source_region_id: string }>
  createdEtlTemplateIds?: string[]
  knowledgeDisabledReason?: string
  llmAdviceState?: 'used' | 'deterministic' | 'degraded'
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
  knowledgeItemIds: string[]
}

type OfficeDockingBatchAdvice = {
  used_llm: boolean
  degraded: boolean
  degradation_code?: string
  model?: string
  advice?: {
    overall_judgment?: string
    reasoning?: string[]
    cautions?: string[]
    questions?: string[]
  }
}

const OFFICE_DOCKING_DECISION_OPTIONS: ChatDecisionOption[] = [
  {
    id: 'recommended',
    label: '按 AI 建议处理',
    description: '写入知识库，并同步高置信业务数据和真实可复用模板',
    message: '按建议处理',
    recommended: true,
  },
  {
    id: 'knowledge-only',
    label: '仅进入知识库',
    description: '保留全部原始资料供 AI 检索，不写业务库或创建模板',
    message: '全部只进入知识库',
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
  return segments.some((segment) => segment === '__MACOSX' || segment.startsWith('.') || segment.startsWith('~$'))
}

function ignoredDirectoryFile(file: File): OfficeDockingIgnoredFile | null {
  const fileName = officeDockingRelativePath(file) || file.name || '未命名文件'
  if (isDirectorySystemFile(file)) return { fileName, reason: '系统或临时文件' }
  if (!isOfficeDockingFileSupported(file.name)) return { fileName, reason: '当前不支持的文件类型' }
  return null
}

function directoryRootLabel(files: File[]): string {
  const path = files.map(officeDockingRelativePath).find((value) => value.includes('/')) || ''
  return path.split('/')[0] || '所选文件夹'
}

function fileStem(fileName: string): string {
  const base =
    String(fileName || '')
      .replace(/\\/g, '/')
      .split('/')
      .pop() || '办公文件'
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
  return item.databaseAction === 'attendance_import' || item.databaseAction === 'shipment_etl_execute' || item.databaseAction === 'universal_etl_execute'
}

function buildBatchInsightMessage(
  items: ChatOfficeDockingReviewItem[],
  sourceLabel: string,
  skippedCount: number,
  batchAdvice?: OfficeDockingBatchAdvice | null,
): string {
  const ready = items.filter((item) => item.status === 'ready')
  const failed = items.filter((item) => item.status === 'error')
  const directDatabase = ready.filter((item) => item.selectedDatabase && isDirectDatabaseAction(item))
  const knowledge = ready.filter((item) => item.selectedKnowledge)
  const templates = ready.filter((item) => item.selectedTemplate && item.templateCandidates?.length)
  const sheetCount = ready.reduce((sum, item) => sum + Number(item.knowledgeRun?.source_features?.sheet_count || 0), 0)
  const llmUsed = ready.filter((item) => item.llmAdviceState === 'used').length
  const llmDegraded = ready.filter((item) => item.llmAdviceState === 'degraded').length
  const details = items.map((item, index) => {
    if (item.status === 'error') return `${index + 1}. ${item.fileName}：分析失败（${item.error || '未知错误'}）`
    const targets = [
      item.selectedKnowledge ? '知识库' : '',
      item.selectedDatabase ? item.databaseTargetLabel : '',
      item.selectedTemplate ? `${item.templateCandidates?.length || 0} 套真实模板` : '',
    ].filter(Boolean)
    const held = item.selectedDatabase ? '' : `；业务库暂缓（${item.databaseDisabledReason || '置信度不足'}）`
    return `${index + 1}. ${item.fileName}：${item.intentLabel}；建议 ${targets.join(' + ') || '仅保留预览'}${held}`
  })
  const skipped = skippedCount ? `；跳过 ${skippedCount} 个系统、不支持或内容重复的文件` : ''
  const llmText = batchAdvice?.used_llm && !batchAdvice.degraded
    ? `模型已在全部文件完成结构预演后进行整批复核（${batchAdvice.model || '当前账号模型'}）；所有写入动作仍由确定性规则校验。`
    : llmDegraded || batchAdvice?.degraded
      ? '整批模型复核暂时不可用，已明确降级为确定性结构分析，未把规则结论伪装成 AI 意见。'
      : llmUsed
        ? `模型已参与 ${llmUsed} 个文件的语义建议；所有写入动作仍由确定性规则校验。`
        : '本批由确定性结构分析形成建议；模型没有参与写入决策。'
  const aiAdvice = asRecord(batchAdvice?.advice)
  const overallJudgment = asString(aiAdvice.overall_judgment).trim()
  const aiReasoning = asArray<unknown>(aiAdvice.reasoning).map((value) => asString(value).trim()).filter(Boolean)
  const aiCautions = asArray<unknown>(aiAdvice.cautions).map((value) => asString(value).trim()).filter(Boolean)
  const aiQuestions = asArray<unknown>(aiAdvice.questions).map((value) => asString(value).trim()).filter(Boolean)
  const aiSection = overallJudgment
    ? [
        '',
        'AI 综合意见：',
        overallJudgment,
        ...aiReasoning.map((value) => `- ${value}`),
        ...aiCautions.map((value) => `- 注意：${value}`),
        ...aiQuestions.map((value) => `- 想和你确认：${value}`),
      ]
    : []
  return [
    `我已经把${sourceLabel}完整分析完了：有效文件 ${ready.length} 个，失败 ${failed.length} 个，共检查 ${sheetCount} 个工作表${skipped}。目前没有写入知识库、数据库或模板库。`,
    '',
    `整体判断：${batchIntentSummary(ready)}。${llmText}`,
    ...aiSection,
    '',
    '逐文件建议：',
    ...details,
    '',
    '我的建议：',
    `- 将 ${knowledge.length} 个原始文件完整进入知识库，保留公式、合并单元格和隐藏工作表等原始证据。`,
    `- 只将 ${directDatabase.length} 个目标明确、预演无阻断错误的文件写入对应业务库。`,
    `- 只保存 ${templates.reduce((sum, item) => sum + (item.templateCandidates?.length || 0), 0)} 套从真实发货单版式提取出的模板；没有真实候选的文件不假装成模板。`,
    '- 财务、对账、物料或无法可靠映射的工作表保留在知识库，暂不写业务表。',
    '',
    '你想怎么处理这批资料？可以选下面的方案，也可以继续用自然语言调整。',
  ].join('\n')
}

async function requestBatchAdvice(
  items: ChatOfficeDockingReviewItem[],
  sourceLabel: string,
): Promise<OfficeDockingBatchAdvice | null> {
  const ready = items.filter((item) => item.status === 'ready' && item.databaseRun && item.knowledgeRun)
  if (!ready.length) return null
  try {
    return await etlApi.batchAdvice({
      source_label: sourceLabel,
      items: ready.map((item) => {
        const detection = asRecord(item.databaseRun?.source_features?.target_detection || item.databaseRun?.details?.target_detection)
        return {
          file_name: item.fileName,
          target_type: item.databaseRun?.target_type || '',
          database_target_label: item.databaseTargetLabel,
          confidence: Number(detection.confidence || 0),
          sheet_count: Number(item.knowledgeRun?.source_features?.sheet_count || 0),
          row_count: item.rowCount,
          new_count: Number(item.databaseRun?.summary.new || 0),
          update_count: Number(item.databaseRun?.summary.update || 0),
          skip_count: Number(item.databaseRun?.summary.skip || 0),
          error_count: Number(item.databaseRun?.summary.error || 0),
          template_count: item.templateCandidates?.length || 0,
          knowledge_ready: Boolean(item.selectedKnowledge),
          database_recommended: Boolean(item.selectedDatabase),
          warnings: item.warnings.slice(0, 20),
        }
      }),
    })
  } catch {
    return {
      used_llm: false,
      degraded: true,
      degradation_code: 'ETL_BATCH_ADVICE_UNAVAILABLE',
      advice: {},
    }
  }
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
      intentSummary: '识别到「明细/月度统计」结构，应写入 ERP 人事考勤，不走客户产品入库',
      databaseTargetLabel: 'ERP 人事考勤',
      databaseAction: 'attendance_import',
      databaseDisabledReason: '',
      selectedDatabase: true,
    }
  }

  if (hasDingtalk || file.includes('考勤')) {
    return {
      intentId: 'attendance_source',
      intentLabel: '钉钉考勤原始表',
      intentSummary: '识别到考勤统计结构，应写入 ERP 人事考勤',
      databaseTargetLabel: 'ERP 人事考勤',
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
  const profileTargets = [...new Set(notes.map((note) => asString(note.profile_target).trim() || 'shipment'))]
  const unsupportedTargets = profileTargets.filter((target) => target !== 'shipment')
  const units = [...new Set(notes.map((n) => asString(n.unit_name).trim()).filter(Boolean))].slice(0, 3)
  const itemCount = notes.reduce((sum, n) => sum + (Number(n.item_count) || asArray(n.items).length || 0), 0)
  item.shipmentEtlPreview = {
    ...preview,
    notes,
    note_count: noteCount,
  }
  item.intentId = 'shipment_delivery'
  item.intentLabel = '送货单/发货单'
  item.databaseTargetLabel = '客户/产品/发货单'
  if (unsupportedTargets.length) {
    const targetText = unsupportedTargets.join('、')
    item.intentSummary = `${asString(preview.message).trim() || `内容指纹识别到 ${noteCount} 张单据`}；后端版式目标为 ${targetText}，当前只允许预览，不能按发货单写库`
    item.databaseAction = ''
    item.databaseDisabledReason = `后端 profile_target=${targetText}，需先配置为 shipment 才能写入客户、产品与发货单`
    item.selectedDatabase = false
    item.warnings = [...item.warnings, item.databaseDisabledReason]
  } else {
    item.intentSummary = asString(preview.message).trim() || `内容指纹识别到 ${noteCount} 张送货单，确认后写入客户、产品与发货单`
    item.databaseAction = 'shipment_etl_execute'
    item.databaseDisabledReason = ''
    // 写库需用户确认勾选；重复导入时默认不勾
    const dup = Number(preview.duplicate_note_count || 0)
    item.selectedDatabase = dup < noteCount
  }
  const dup = Number(preview.duplicate_note_count || 0)
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

function disableUnverifiedShipmentWrite(item: ChatOfficeDockingReviewItem): void {
  if (item.intentId !== 'shipment_delivery') return
  item.databaseAction = ''
  item.selectedDatabase = false
  item.databaseDisabledReason = '后端未返回可执行的发货单 profile_target，当前仅允许读取和归档模板'
  item.intentSummary = `${item.intentSummary}；${item.databaseDisabledReason}`
  item.warnings = [...item.warnings, item.databaseDisabledReason]
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
  const unsupportedTargets = [
    ...new Set(
      asArray<ShipmentEtlNotePreview>(item.shipmentEtlPreview?.notes)
        .map((note) => asString(note.profile_target).trim() || 'shipment')
        .filter((target) => target !== 'shipment'),
    ),
  ]
  if (unsupportedTargets.length) {
    throw new Error(`后端 profile_target=${unsupportedTargets.join('、')}，当前只允许预览，不能写入发货单数据库`)
  }
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

function archivedTemplateId(result?: Record<string, unknown>): string {
  const template = asRecord(result?.template)
  const id = String(template.id ?? '').trim()
  if (id) return id
  const dbId = String(template.db_id ?? '').trim()
  return dbId ? `db:${dbId}` : ''
}

async function rollbackArchivedTemplate(result?: Record<string, unknown>): Promise<Record<string, unknown>> {
  const id = archivedTemplateId(result)
  if (!id) throw new Error('模板归档响应未返回模板 id，无法自动回滚')
  await primeCsrfCookie()
  const res = await apiFetch('/api/templates/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body?.success === false) {
    throw new Error(String(body?.message || body?.error || `模板回滚失败 HTTP ${res.status}`))
  }
  return asRecord(body)
}

async function ingestAttendanceDatabase(item: ChatOfficeDockingReviewItem): Promise<Record<string, unknown>> {
  if (!item.upload?.file_path) throw new Error('缺少已上传文件路径')
  await primeCsrfCookie()
  const res = await apiFetch('/api/platform-shell/office/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      intent: 'attendance',
      file_path: item.upload.file_path,
      workspace_root: item.upload.workspace_root,
      source_name: item.fileName,
    }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body?.success === false) {
    throw new Error(String(body?.detail || body?.error || body?.message || `考勤入库失败 HTTP ${res.status}`))
  }
  return asRecord(body?.data || body)
}

const ETL_TARGET_LABELS: Record<string, string> = {
  attendance: 'ERP 人事考勤',
  customer_products: '客户/产品库',
  customers: '客户库',
  products: '产品库',
  purchase_orders: '采购单库',
  shipment_records: '客户/产品/发货单',
}

const ETL_INTENT_LABELS: Record<string, string> = {
  attendance: '考勤业务资料',
  customer_products: '客户/产品业务资料',
  customers: '客户资料',
  products: '产品资料',
  purchase_orders: '采购业务资料',
  shipment_records: '送货单/发货单资料',
  knowledge: '知识资料',
}

type PreparedCorpusFile = {
  file: File
  displayName: string
  upload: NonNullable<ChatOfficeDockingReviewItem['etlUpload']>
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

async function waitForEtlRun(run: EtlRun, cancelled: () => boolean): Promise<EtlRun> {
  const terminal = new Set(['preview_ready', 'completed', 'failed', 'interrupted'])
  let current = run
  for (let attempt = 0; !terminal.has(current.status) && attempt < 240; attempt += 1) {
    if (cancelled()) throw new Error('用户停止了本次分析')
    await sleep(500)
    current = await etlApi.run(current.id)
  }
  if (!terminal.has(current.status)) throw new Error('分析超时，任务仍在后台运行，请稍后重试')
  return current
}

async function executeEtlRun(run: EtlRun): Promise<EtlRun> {
  let current = run.status === 'completed' ? run : await etlApi.execute(run.id)
  for (let attempt = 0; !['completed', 'failed', 'interrupted'].includes(current.status) && attempt < 240; attempt += 1) {
    await sleep(500)
    current = await etlApi.run(current.id)
  }
  if (current.status !== 'completed' || current.execution_integrity?.status === 'drifted') throw new Error(runFailure(current))
  return current
}

function runFailure(run: EtlRun): string {
  if (run.execution_integrity?.status === 'drifted') {
    const failures = run.execution_integrity.failures || []
    const details = failures
      .slice(0, 8)
      .map((failure) => `${failure.source_sheet || '工作表'} 第 ${failure.source_row || '?'} 行：${failure.message}`)
    const remaining = Math.max(0, Number(run.execution_integrity.failure_count || failures.length) - details.length)
    return `执行结果复查失败：${details.join('；')}${remaining ? `；另有 ${remaining} 行失败` : ''}`
  }
  const receiptFailures = Array.isArray(run.receipt?.execution_failures)
    ? (run.receipt.execution_failures as Array<Record<string, unknown>>)
    : []
  if (receiptFailures.length) {
    return receiptFailures
      .map(
        (failure) =>
          `${String(failure.source_sheet || '工作表')} 第 ${String(failure.source_row || '?')} 行：${String(failure.message || '执行失败')}`,
      )
      .join('；')
  }
  return run.error?.message || `${run.target_type} 预演${run.status === 'interrupted' ? '被中断' : '失败'}`
}

function etlWarnings(run?: EtlRun): string[] {
  if (!run) return []
  return asArray<Record<string, unknown>>(run.details?.warnings)
    .map((warning) => asString(warning.message).trim())
    .filter(Boolean)
}

function etlLlmAdviceState(run?: EtlRun): ChatOfficeDockingReviewItem['llmAdviceState'] {
  if (!run) return 'deterministic'
  const structure = asRecord(run.source_features?.llm_structure)
  const mapping = asRecord(run.source_features?.llm_mapping)
  if (structure.degraded === true || mapping.degraded === true) return 'degraded'
  if (structure.used_llm === true || mapping.used_llm === true) return 'used'
  return 'deterministic'
}

function shipmentTemplateCandidates(run?: EtlRun): Array<{ name: string; source_region_id: string }> {
  return asArray<Record<string, unknown>>(run?.source_features?.shipment_template_candidates)
    .map((candidate) => ({
      name: asString(candidate.name).trim(),
      source_region_id: asString(candidate.source_region_id).trim(),
    }))
    .filter((candidate) => candidate.name && candidate.source_region_id)
}

function applyCorpusRuns(item: ChatOfficeDockingReviewItem, databaseRun: EtlRun, knowledgeRun: EtlRun, linkedDatabaseRuns: EtlRun[] = []): void {
  item.databaseRun = databaseRun
  item.databaseRuns = [databaseRun, ...linkedDatabaseRuns]
  item.knowledgeRun = knowledgeRun
  const databaseReady = item.databaseRuns.every((run) => run.status === 'preview_ready')
  const knowledgeReady = knowledgeRun.status === 'preview_ready'
  if (!databaseReady && !knowledgeReady) {
    throw new Error(`数据库预演：${runFailure(databaseRun)}；知识库预演：${runFailure(knowledgeRun)}`)
  }

  const detection = asRecord(databaseRun.source_features?.target_detection || databaseRun.details?.target_detection)
  const confidence = Number(detection.confidence || 0)
  const actionable = item.databaseRuns.reduce((sum, run) => sum + Number(run.summary.new || 0) + Number(run.summary.update || 0), 0)
  const blockingErrors = item.databaseRuns.reduce((sum, run) => sum + Number(run.summary.error || 0), 0)
  item.databaseTargetLabel = ETL_TARGET_LABELS[databaseRun.target_type] || databaseRun.target_type
  item.databaseAction = databaseReady ? 'universal_etl_execute' : ''
  item.selectedDatabase = databaseReady && confidence >= 0.7 && actionable > 0 && blockingErrors === 0
  item.databaseDisabledReason = item.selectedDatabase
    ? ''
    : !databaseReady
      ? runFailure(databaseRun)
      : confidence < 0.7
        ? `自动识别置信度仅 ${Math.round(confidence * 100)}%，需人工指定业务目标`
        : blockingErrors
          ? `预演发现 ${blockingErrors} 条阻断错误，暂不允许写库`
          : '没有新增或可更新的业务记录'

  item.selectedKnowledge = knowledgeReady && Number(knowledgeRun.summary.error || 0) === 0 && Number(knowledgeRun.summary.skip || 0) === 0
  item.knowledgeDisabledReason = item.selectedKnowledge
    ? ''
    : !knowledgeReady
      ? runFailure(knowledgeRun)
      : Number(knowledgeRun.summary.skip || 0)
        ? '内容指纹已存在，知识库会幂等跳过'
        : '知识库预演存在阻断错误'

  item.templateCandidates = shipmentTemplateCandidates(databaseRun)
  item.selectedTemplate = item.templateCandidates.length > 0
  item.templateTargetLabel = item.selectedTemplate ? '真实发货单版式' : '无可保存模板'
  item.templateName = item.templateCandidates[0]?.name || ''
  item.templateScope = item.selectedTemplate ? 'orders' : ''
  item.databaseAction = item.selectedDatabase || databaseReady ? 'universal_etl_execute' : ''

  item.intentLabel = ETL_INTENT_LABELS[databaseRun.target_type] || '混合办公资料'
  item.intentId = databaseRun.target_type === 'shipment_records' ? 'shipment_delivery' : databaseRun.target_type === 'customer_products' ? 'customer_product' : 'generic_table'
  item.intentSummary = item.selectedDatabase
    ? `业务目标置信度 ${Math.round(confidence * 100)}%，预演新增 ${databaseRun.summary.new}、更新 ${databaseRun.summary.update}、跳过 ${databaseRun.summary.skip}`
    : `已完成业务结构预演，但${item.databaseDisabledReason}`
  const inventory = asArray<Record<string, unknown>>(knowledgeRun.source_features?.workbook_inventory)
  item.rowCount = item.databaseRuns.reduce((sum, run) => sum + run.total_rows, 0)
  item.fieldNames = asArray<Record<string, unknown>>(databaseRun.draft?.field_mappings)
    .map((mapping) => asString(mapping.source).trim())
    .filter(Boolean)
    .slice(0, 40)
  item.sampleRows = []
  item.llmAdviceState = etlLlmAdviceState(databaseRun)
  item.warnings = [...item.databaseRuns.flatMap((run) => etlWarnings(run)), ...etlWarnings(knowledgeRun)]
  if (!databaseReady) {
    item.warnings.push(...item.databaseRuns.filter((run) => run.status !== 'preview_ready').map((run) => `${ETL_TARGET_LABELS[run.target_type] || run.target_type}预演失败：${runFailure(run)}`))
  }
  if (!knowledgeReady) item.warnings.push(`知识库预演失败：${runFailure(knowledgeRun)}`)
  if (item.llmAdviceState === 'degraded') item.warnings.push('模型语义建议不可用；当前结论来自确定性结构分析，未伪装成 AI 结果')
  item.summary = `已完整检查 ${inventory.length} 个工作表；业务预演 ${item.rowCount} 行${linkedDatabaseRuns.length ? '（含客户/产品关系附表）' : ''}；知识库 ${knowledgeRun.summary.new ? '可新增原文件' : '无新增'}；真实模板候选 ${item.templateCandidates.length} 套`
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
  const officeDockingProgressPhase = ref<OfficeDockingProgressPhase>('idle')
  const officeDockingProgressSourceLabel = ref('')
  const officeDockingProgressTotal = ref(0)
  const officeDockingProgressCurrentIndex = ref(0)
  const officeDockingProgressCurrentFile = ref('')
  const officeDockingProgressIgnored = ref<OfficeDockingIgnoredFile[]>([])
  const officeDockingProgressStartedAt = ref(0)
  const officeDockingProgressNow = ref(0)
  const officeDockingCancelRequested = ref(false)
  let officeDockingProgressTimer: number | null = null
  const officeDockingPendingCount = computed(
    () =>
      officeDockingReviewItems.value.filter(
        (item) => item.status === 'ready' && item.commitStatus !== 'committed' && item.commitStatus !== 'skipped',
      ).length,
  )
  const officeDockingProgress = computed<ChatOfficeDockingProgress | null>(() => {
    if (officeDockingProgressPhase.value === 'idle') return null
    const completed = officeDockingReviewItems.value.filter((item) => item.status !== 'running').length
    const success = officeDockingReviewItems.value.filter((item) => item.status === 'ready').length
    const failed = officeDockingReviewItems.value.filter((item) => item.status === 'error').length
    const failures = officeDockingReviewItems.value
      .filter((item) => item.status === 'error')
      .map((item) => ({ fileName: item.fileName, reason: item.error || '未知错误' }))
    const total = officeDockingProgressTotal.value
    return {
      phase: officeDockingProgressPhase.value,
      sourceLabel: officeDockingProgressSourceLabel.value,
      total,
      completed,
      currentIndex: officeDockingProgressCurrentIndex.value,
      currentFile: officeDockingProgressCurrentFile.value,
      success,
      failed,
      failures,
      ignored: officeDockingProgressIgnored.value,
      elapsedSeconds: officeDockingProgressStartedAt.value
        ? Math.max(0, Math.floor((officeDockingProgressNow.value - officeDockingProgressStartedAt.value) / 1000))
        : 0,
      percent: total ? Math.min(100, Math.round((completed / total) * 100)) : 100,
    }
  })

  function stopOfficeDockingClock() {
    if (officeDockingProgressTimer !== null) {
      window.clearInterval(officeDockingProgressTimer)
      officeDockingProgressTimer = null
    }
    officeDockingProgressNow.value = Date.now()
  }

  function startOfficeDockingClock() {
    stopOfficeDockingClock()
    officeDockingProgressStartedAt.value = Date.now()
    officeDockingProgressNow.value = officeDockingProgressStartedAt.value
    officeDockingProgressTimer = window.setInterval(() => {
      officeDockingProgressNow.value = Date.now()
    }, 1000)
  }

  if (getCurrentScope()) onScopeDispose(stopOfficeDockingClock)

  function cancelOfficeDockingReading() {
    if (!['inventory', 'reading', 'reasoning', 'planning'].includes(officeDockingProgressPhase.value)) return
    officeDockingCancelRequested.value = true
    officeDockingProgressPhase.value = 'stopping'
  }

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
      selectedKnowledge: false,
      templateName: `${fileStem(displayName)} · 办公文件模板`,
      templateScope: '',
      templateTargetLabel: '办公文件模板',
      templateCommitStatus: '',
      databaseCommitStatus: '',
      knowledgeCommitStatus: '',
      summary: '正在读取文件内容…',
      warnings: [],
      error: '',
      templateError: '',
      databaseError: '',
      knowledgeError: '',
      rollbackError: '',
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
      item.summary = '文件已就绪，正在读取内容…'
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
          else disableUnverifiedShipmentWrite(item)
        } catch {
          // 预览失败不阻断读取和模板归档，但不能依赖字段启发式直接写库。
          disableUnverifiedShipmentWrite(item)
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

  async function analyzeCorpusFile(prepared: PreparedCorpusFile): Promise<void> {
    const item: ChatOfficeDockingReviewItem = {
      id: newItemId(),
      fileName: prepared.displayName,
      employeeId: 'universal-etl',
      employeeLabel: 'AI 对接引擎',
      kindLabel: prepared.file.name.split('.').pop()?.toUpperCase() || '办公文件',
      status: 'running',
      commitStatus: '',
      intentId: 'pending',
      intentLabel: '正在判断',
      intentSummary: '正在同时生成业务数据库预演和知识库预演',
      databaseTargetLabel: '',
      databaseAction: '',
      databaseDisabledReason: '',
      selectedTemplate: false,
      selectedDatabase: false,
      selectedKnowledge: false,
      templateName: '',
      templateScope: '',
      templateTargetLabel: '无可保存模板',
      templateCommitStatus: '',
      databaseCommitStatus: '',
      knowledgeCommitStatus: '',
      summary: '正在读取全部工作表、公式、隐藏页和业务区域…',
      warnings: [],
      error: '',
      templateError: '',
      databaseError: '',
      knowledgeError: '',
      rollbackError: '',
      outputFiles: [],
      sourceFile: prepared.file,
      etlUpload: prepared.upload,
      fieldNames: [],
      sampleRows: [],
      rowCount: 0,
      textPreview: '',
      templateCandidates: [],
      createdEtlTemplateIds: [],
      knowledgeDisabledReason: '',
      llmAdviceState: 'deterministic',
    }
    officeDockingReviewItems.value.push(item)
    touchItems()
    try {
      officeDockingProgressPhase.value = 'reasoning'
      const [databaseStart, knowledgeStart] = await Promise.all([
        etlApi.preview({ upload_id: prepared.upload.upload_id, target_type: 'auto', llm_advice_enabled: false }),
        etlApi.preview({ upload_id: prepared.upload.upload_id, target_type: 'knowledge', llm_advice_enabled: false }),
      ])
      const [databaseRun, knowledgeRun] = await Promise.all([
        waitForEtlRun(databaseStart, () => officeDockingCancelRequested.value),
        waitForEtlRun(knowledgeStart, () => officeDockingCancelRequested.value),
      ])
      const linkedPreview = asRecord(databaseRun.details?.linked_customer_products_preview)
      const linkedRunId = asString(linkedPreview.run_id).trim()
      const linkedDatabaseRuns = linkedRunId
        ? [await waitForEtlRun(await etlApi.run(linkedRunId), () => officeDockingCancelRequested.value)]
        : []
      applyCorpusRuns(item, databaseRun, knowledgeRun, linkedDatabaseRuns)
      item.status = 'ready'
    } catch (error) {
      item.status = 'error'
      item.summary = ''
      item.error = error instanceof Error ? error.message : String(error || '文件分析失败')
    } finally {
      touchItems()
    }
  }

  function recordCorpusFailure(file: File, displayName: string, error: unknown): void {
    officeDockingReviewItems.value.push({
      id: newItemId(),
      fileName: displayName,
      employeeId: 'universal-etl',
      employeeLabel: 'AI 对接引擎',
      kindLabel: file.name.split('.').pop()?.toUpperCase() || '办公文件',
      status: 'error',
      commitStatus: '',
      intentId: 'pending',
      intentLabel: '分析失败',
      intentSummary: '',
      databaseTargetLabel: '',
      databaseAction: '',
      databaseDisabledReason: '',
      selectedTemplate: false,
      selectedDatabase: false,
      selectedKnowledge: false,
      templateName: '',
      templateScope: '',
      templateTargetLabel: '无可保存模板',
      templateCommitStatus: '',
      databaseCommitStatus: '',
      knowledgeCommitStatus: '',
      summary: '',
      warnings: [],
      error: error instanceof Error ? error.message : String(error || '上传失败'),
      outputFiles: [],
      sourceFile: file,
      fieldNames: [],
      sampleRows: [],
      rowCount: 0,
      textPreview: '',
    })
    touchItems()
  }

  async function onOfficeDockingFileChange(event: Event) {
    const input = event.target as HTMLInputElement | null
    const selectedFiles = Array.from(input?.files || [])
    const isDirectorySelection = Boolean(
      input?.hasAttribute('webkitdirectory') || selectedFiles.some((file) => officeDockingRelativePath(file).includes('/')),
    )
    const folderLabel = directoryRootLabel(selectedFiles)
    const ignoredFiles = isDirectorySelection
      ? selectedFiles.map(ignoredDirectoryFile).filter((item): item is OfficeDockingIgnoredFile => Boolean(item))
      : []
    const files = isDirectorySelection ? selectedFiles.filter((file) => !ignoredDirectoryFile(file)) : selectedFiles
    let skippedCount = ignoredFiles.length
    if (input) input.value = ''
    if (!selectedFiles.length) return
    officeDockingReviewItems.value = []
    officeDockingAwaitingDecision.value = false
    officeDockingBatchPlan.value = null
    officeDockingCancelRequested.value = false
    officeDockingProgressSourceLabel.value = isDirectorySelection ? `文件夹「${folderLabel}」` : '所选文件'
    officeDockingProgressTotal.value = files.length
    officeDockingProgressCurrentIndex.value = 0
    officeDockingProgressCurrentFile.value = ''
    officeDockingProgressIgnored.value = ignoredFiles
    if (!files.length) {
      officeDockingProgressPhase.value = 'completed'
      officeDockingProgressStartedAt.value = Date.now()
      officeDockingProgressNow.value = officeDockingProgressStartedAt.value
      const ignoredSummary = ignoredFiles.map((item) => `「${item.fileName}」：${item.reason}`).join('；')
      await deps.addAndSaveMessage(
        `文件夹「${folderLabel}」中没有可读取的办公文件。${ignoredSummary ? `已跳过：${ignoredSummary}。` : ''}没有归档模板，也没有写入数据库。`,
        'ai',
      )
      return
    }
    officeDockingPanelOpen.value = mode === 'review'
    officeDockingProcessing.value = true
    officeDockingProgressPhase.value = 'reading'
    startOfficeDockingClock()
    const skippedText = skippedCount ? `，另有 ${skippedCount} 个文件已跳过（可在进度卡查看原因）` : ''
    const sourceText = isDirectorySelection ? `文件夹「${folderLabel}」中的 ` : ''
    await deps.addAndSaveMessage(
      mode === 'conversation'
        ? `已收到${sourceText}${files.length} 个可读取文件${skippedText}。我会先做内容指纹去重，再完整分析工作表和业务关系，最后一次和你商量怎么进入知识库、数据库和模板库；分析期间不会写入任何目标。`
        : `已收到${sourceText}${files.length} 个可读取文件${skippedText}，现在开始阅读。`,
      'ai',
    )
    try {
      if (mode === 'conversation') {
        officeDockingProgressPhase.value = 'inventory'
        const batchId = typeof globalThis.crypto?.randomUUID === 'function'
          ? globalThis.crypto.randomUUID()
          : `10000000-1000-4000-8000-${Date.now().toString().padStart(12, '0').slice(-12)}`
        const seenContent = new Map<string, string>()
        const prepared: PreparedCorpusFile[] = []
        for (const [index, file] of files.entries()) {
          if (officeDockingCancelRequested.value) break
          const displayName = isDirectorySelection ? officeDockingRelativePath(file) : file.name
          officeDockingProgressCurrentIndex.value = index + 1
          officeDockingProgressCurrentFile.value = displayName
          try {
            const upload = await etlApi.upload(file, { batchId, relativePath: displayName })
            const duplicateOf = seenContent.get(upload.sha256)
            if (duplicateOf) {
              officeDockingProgressIgnored.value.push({ fileName: displayName, reason: `内容与「${duplicateOf}」完全相同` })
              continue
            }
            seenContent.set(upload.sha256, displayName)
            prepared.push({ file, displayName, upload })
          } catch (error) {
            recordCorpusFailure(file, displayName, error)
          }
        }
        skippedCount = officeDockingProgressIgnored.value.length
        officeDockingProgressTotal.value = prepared.length + officeDockingReviewItems.value.length
        officeDockingProgressPhase.value = 'reading'
        let cursor = 0
        async function worker() {
          while (cursor < prepared.length && !officeDockingCancelRequested.value) {
            const index = cursor++
            const current = prepared[index]
            officeDockingProgressCurrentIndex.value = index + 1
            officeDockingProgressCurrentFile.value = current.displayName
            await analyzeCorpusFile(current)
          }
        }
        await Promise.all(Array.from({ length: Math.min(2, Math.max(1, prepared.length)) }, () => worker()))
      } else {
        for (const [index, file] of files.entries()) {
          if (officeDockingCancelRequested.value) break
          officeDockingProgressCurrentIndex.value = index + 1
          officeDockingProgressCurrentFile.value = isDirectorySelection ? officeDockingRelativePath(file) : file.name
          await analyzeFile(file, isDirectorySelection ? officeDockingRelativePath(file) : file.name)
        }
      }
    } finally {
      officeDockingProcessing.value = false
      stopOfficeDockingClock()
    }
    if (officeDockingCancelRequested.value) {
      officeDockingProgressPhase.value = 'cancelled'
      const completed = officeDockingReviewItems.value.filter((item) => item.status !== 'running').length
      await deps.addAndSaveMessage(
        `已停止这次分析：完成 ${completed}/${officeDockingProgressTotal.value} 个。已生成的都只是预演，没有写入知识库、数据库或模板库。`,
        'ai',
      )
      return
    }
    officeDockingProgressPhase.value = 'completed'
    if (mode === 'conversation') {
      officeDockingProgressPhase.value = 'planning'
      officeDockingAwaitingDecision.value = officeDockingReviewItems.value.some((item) => item.status === 'ready')
      const sourceLabel = isDirectorySelection ? `文件夹「${folderLabel}」里的文件` : '这批文件'
      const batchAdvice = await requestBatchAdvice(officeDockingReviewItems.value, sourceLabel)
      await deps.addAndSaveMessage(buildBatchInsightMessage(officeDockingReviewItems.value, sourceLabel, skippedCount, batchAdvice), 'ai', {
        decisionOptions: OFFICE_DOCKING_DECISION_OPTIONS,
      })
      officeDockingProgressPhase.value = 'completed'
      return
    }
    const firstReady = officeDockingReviewItems.value.find((item) => item.status === 'ready' && !item.commitStatus)
    if (firstReady) await deps.addAndSaveMessage(buildReviewAdviceMessage(firstReady), 'ai')
  }

  function toggleOfficeDockingTarget(id: string, target: OfficeDockingTarget, enabled: boolean) {
    const item = officeDockingReviewItems.value.find((row) => row.id === id)
    if (!item) return
    if (target === 'template') item.selectedTemplate = enabled
    if (target === 'database' && (item.excelAnalysis || item.databaseRun) && item.databaseAction) {
      item.selectedDatabase = enabled
    }
    if (target === 'knowledge' && item.knowledgeRun?.status === 'preview_ready') item.selectedKnowledge = enabled
    touchItems()
  }

  function updateOfficeDockingTemplateName(id: string, value: string) {
    const item = officeDockingReviewItems.value.find((row) => row.id === id)
    if (!item || item.commitStatus === 'committing') return
    item.templateName = String(value || '').trimStart()
    touchItems()
  }

  function currentReviewItem(): ChatOfficeDockingReviewItem | undefined {
    return officeDockingReviewItems.value.find((item) => item.commitStatus !== 'committed' && item.commitStatus !== 'skipped')
  }

  async function announceNextAdvice(): Promise<void> {
    const next = currentReviewItem()
    if (next?.status === 'ready') await deps.addAndSaveMessage(buildReviewAdviceMessage(next), 'ai')
    if (!next && officeDockingReviewItems.value.length) {
      await deps.addAndSaveMessage('[对接] 本批文件审核完成。', 'ai')
    }
  }

  async function executeCorpusItem(item: ChatOfficeDockingReviewItem): Promise<void> {
    item.commitStatus = 'committing'
    item.error = ''
    item.templateError = ''
    item.databaseError = ''
    item.knowledgeError = ''
    item.rollbackError = ''
    const executedRuns: Array<{ target: 'database' | 'knowledge'; run: EtlRun }> = []
    const createdTemplateIds: string[] = []
    let stage: 'database' | 'knowledge' | 'template' = 'database'
    touchItems()
    try {
      if (item.selectedDatabase) {
        const availableRuns = item.databaseRuns?.length ? item.databaseRuns : item.databaseRun ? [item.databaseRun] : []
        if (!availableRuns.length || availableRuns.some((run) => run.status !== 'preview_ready')) throw new Error('缺少可执行的数据库预演')
        item.databaseCommitStatus = 'committing'
        touchItems()
        const orderedRuns = availableRuns.length > 1 ? [...availableRuns.slice(1), availableRuns[0]] : availableRuns
        const completedRuns: EtlRun[] = []
        for (const run of orderedRuns) {
          const completed = await executeEtlRun(run)
          completedRuns.push(completed)
          executedRuns.push({ target: 'database', run: completed })
        }
        item.databaseRuns = completedRuns
        item.databaseRun = completedRuns.find((run) => run.id === item.databaseRun?.id) || item.databaseRun
        item.databaseCommitStatus = 'committed'
      } else {
        item.databaseCommitStatus = 'skipped'
      }

      stage = 'knowledge'
      if (item.selectedKnowledge) {
        if (!item.knowledgeRun || item.knowledgeRun.status !== 'preview_ready') throw new Error('缺少可执行的知识库预演')
        item.knowledgeCommitStatus = 'committing'
        touchItems()
        item.knowledgeRun = await executeEtlRun(item.knowledgeRun)
        executedRuns.push({ target: 'knowledge', run: item.knowledgeRun })
        item.knowledgeCommitStatus = 'committed'
      } else {
        item.knowledgeCommitStatus = 'skipped'
      }

      stage = 'template'
      if (item.selectedTemplate) {
        if (!item.databaseRun || !item.templateCandidates?.length) throw new Error('没有经过预演的真实模板候选')
        item.templateCommitStatus = 'committing'
        touchItems()
        for (const candidate of item.templateCandidates) {
          const saved = await etlApi.saveShipmentTemplate(item.databaseRun.id, candidate.name, candidate.source_region_id)
          createdTemplateIds.push(saved.template_id)
        }
        item.createdEtlTemplateIds = createdTemplateIds
        item.templateCommitStatus = 'committed'
      } else {
        item.templateCommitStatus = 'skipped'
      }
      item.commitStatus = 'committed'
      item.summary = `执行完成：数据库 ${item.selectedDatabase ? '成功' : '未选'}；知识库 ${item.selectedKnowledge ? '成功' : '未选'}；模板 ${item.selectedTemplate ? `${createdTemplateIds.length} 套成功` : '未选'}`
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error || '执行失败')
      if (stage === 'database') {
        item.databaseCommitStatus = 'failed'
        item.databaseError = reason
      } else if (stage === 'knowledge') {
        item.knowledgeCommitStatus = 'failed'
        item.knowledgeError = reason
      } else {
        item.templateCommitStatus = 'failed'
        item.templateError = reason
      }
      const rollbackFailures: string[] = []
      for (const templateId of [...createdTemplateIds].reverse()) {
        try {
          await etlApi.deleteTemplate(templateId)
        } catch (rollbackError) {
          rollbackFailures.push(`模板 ${templateId}：${rollbackError instanceof Error ? rollbackError.message : String(rollbackError)}`)
        }
      }
      if (createdTemplateIds.length && !rollbackFailures.some((failure) => failure.startsWith('模板'))) item.templateCommitStatus = 'rolled_back'
      for (const executed of [...executedRuns].reverse()) {
        try {
          await etlApi.rollback(executed.run.id)
          if (executed.target === 'database') item.databaseCommitStatus = 'rolled_back'
          if (executed.target === 'knowledge') item.knowledgeCommitStatus = 'rolled_back'
        } catch (rollbackError) {
          rollbackFailures.push(`${executed.target === 'database' ? '数据库' : '知识库'}：${rollbackError instanceof Error ? rollbackError.message : String(rollbackError)}`)
        }
      }
      item.rollbackError = rollbackFailures.join('；')
      item.commitStatus = rollbackFailures.length ? 'partial' : 'failed'
      item.error = rollbackFailures.length
        ? `${stage === 'database' ? '数据库' : stage === 'knowledge' ? '知识库' : '模板库'}失败：${reason}；部分回滚失败：${item.rollbackError}`
        : `${stage === 'database' ? '数据库' : stage === 'knowledge' ? '知识库' : '模板库'}失败：${reason}；本文件本次已写入内容已自动回滚`
    } finally {
      touchItems()
    }
  }

  async function executeOfficeDockingItem(item: ChatOfficeDockingReviewItem): Promise<void> {
    if (item.databaseAction === 'universal_etl_execute' || item.databaseRun || item.knowledgeRun) {
      await executeCorpusItem(item)
      return
    }
    item.commitStatus = 'committing'
    item.error = ''
    item.templateError = ''
    item.databaseError = ''
    item.rollbackError = ''
    let templateCreatedThisAttempt = false
    touchItems()
    try {
      if (item.selectedTemplate && item.templateCommitStatus !== 'committed') {
        item.templateCommitStatus = 'committing'
        touchItems()
        try {
          item.templateResult = await archiveTemplateLibrary(item)
          item.templateCommitStatus = 'committed'
          templateCreatedThisAttempt = true
        } catch (error) {
          item.templateCommitStatus = 'failed'
          item.templateError = error instanceof Error ? error.message : String(error || '模板库归档失败')
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
          item.databaseError = error instanceof Error ? error.message : String(error || '数据库写入失败')
          if (templateCreatedThisAttempt) {
            try {
              await rollbackArchivedTemplate(item.templateResult)
              item.templateCommitStatus = 'rolled_back'
            } catch (rollbackError) {
              item.rollbackError = rollbackError instanceof Error ? rollbackError.message : String(rollbackError || '模板回滚失败')
            }
          }
          throw error
        }
      }
      item.commitStatus = 'committed'
    } catch (err) {
      const failure = err instanceof Error ? err.message : String(err || '提交失败')
      const templateStillCommitted = item.templateCommitStatus === 'committed'
      item.commitStatus = templateStillCommitted ? 'partial' : 'failed'
      if (item.databaseError && item.templateCommitStatus === 'rolled_back') {
        item.error = `${item.databaseError}；本次新建模板已自动回滚，没有留下半成品`
      } else if (item.databaseError && templateStillCommitted) {
        const rollbackText = item.rollbackError ? `；自动回滚失败：${item.rollbackError}` : ''
        item.error = `模板库已成功，${item.databaseTargetLabel || '数据库'}失败：${item.databaseError}${rollbackText}`
      } else {
        item.error = failure
      }
    } finally {
      touchItems()
    }
  }

  async function confirmOfficeDockingReview() {
    const item = currentReviewItem()
    if (!item || item.status !== 'ready' || item.commitStatus === 'committing' || (!item.selectedTemplate && !item.selectedDatabase && !item.selectedKnowledge)) return
    await executeOfficeDockingItem(item)
    if (item.commitStatus === 'failed' || item.commitStatus === 'partial') {
      await deps.addAndSaveMessage(`[对接] 「${item.fileName}」处理失败：${item.error}。请调整后重试或跳过。`, 'ai')
      return
    }
    const targets = [item.selectedKnowledge ? '知识库' : '', item.selectedTemplate ? '模板库' : '', item.selectedDatabase ? item.databaseTargetLabel : ''].filter(Boolean)
    await deps.addAndSaveMessage(`[对接] 「${item.fileName}」已处理到 ${targets.join('、')}。`, 'ai')
    await announceNextAdvice()
  }

  function readyBatchItems(): ChatOfficeDockingReviewItem[] {
    return officeDockingReviewItems.value.filter((item) => item.status === 'ready')
  }

  function recommendedDatabaseItems(items: ChatOfficeDockingReviewItem[]): ChatOfficeDockingReviewItem[] {
    return items.filter((item) => item.selectedDatabase && isDirectDatabaseAction(item))
  }

  function recommendedKnowledgeItems(items: ChatOfficeDockingReviewItem[]): ChatOfficeDockingReviewItem[] {
    return items.filter((item) => item.selectedKnowledge && item.knowledgeRun?.status === 'preview_ready')
  }

  function recommendedTemplateItems(items: ChatOfficeDockingReviewItem[]): ChatOfficeDockingReviewItem[] {
    return items.filter((item) => item.selectedTemplate && Boolean(item.templateCandidates?.length))
  }

  function makeBatchPlan(
    label: string,
    templateItems: ChatOfficeDockingReviewItem[],
    databaseItems: ChatOfficeDockingReviewItem[],
    knowledgeItems: ChatOfficeDockingReviewItem[] = [],
  ): OfficeDockingBatchPlan {
    return {
      label,
      templateItemIds: templateItems.map((item) => item.id),
      databaseItemIds: databaseItems.map((item) => item.id),
      knowledgeItemIds: knowledgeItems.map((item) => item.id),
    }
  }

  function resolveConversationPlan(message: string): OfficeDockingBatchPlan | 'cancel' | null {
    const normalized = String(message || '').replace(/\s+/g, '')
    const items = readyBatchItems()
    if (!normalized || !items.length) return null
    if (/^(先不处理|暂不处理|取消这批|不要处理|先放着|全部跳过)[。！!]*$/.test(normalized)) return 'cancel'
    if (/^(按建议处理|就按(这个|你的|AI的)?建议处理?|照你的建议处理?|按你说的(方案)?处理?|都按你说的办)[。！!]*$/.test(normalized)) {
      return makeBatchPlan('按 AI 建议处理', recommendedTemplateItems(items), recommendedDatabaseItems(items), recommendedKnowledgeItems(items))
    }
    if (
      /(全部|所有|这批).*(只进入|仅进入|只放|只存).*(知识库)/.test(normalized) ||
      /(全部|所有|这批).*(知识库).*(不入库|不写业务库|不建模板)/.test(normalized)
    ) {
      return makeBatchPlan('全部只进入知识库', [], [], recommendedKnowledgeItems(items))
    }
    if (
      /(全部|所有|这批).*(只归档|仅归档|只放|只存).*(模板|模版)/.test(normalized) ||
      /(全部|所有|这批).*(模板|模版).*(不入库|不写库|不写数据库)/.test(normalized) ||
      (!/[吗么？?]|能否|可以不/.test(normalized) &&
        /(全部|所有|这批|都|统一).*(归档|保存|存到|放到|收进).*(模板|模版)/.test(normalized) &&
        !/(入库|同步|写入).*(数据库|业务库|对应库)/.test(normalized))
    ) {
      return makeBatchPlan('只保存真实模板候选', recommendedTemplateItems(items), [], [])
    }
    if (/(发货单|送货单).*(入库|同步).*(其余|其他).*(归档|模板|模版)/.test(normalized)) {
      const shipments = items.filter((item) => item.intentId === 'shipment_delivery' && isDirectDatabaseAction(item))
      return makeBatchPlan('发货单入库，其余进入知识库', recommendedTemplateItems(items), shipments, recommendedKnowledgeItems(items))
    }
    if (/(考勤).*(入库|同步).*(其余|其他).*(归档|模板|模版)/.test(normalized)) {
      const attendance = items.filter(
        (item) => (item.intentId === 'attendance_roster' || item.intentId === 'attendance_source') && isDirectDatabaseAction(item),
      )
      return makeBatchPlan('考勤表入库，其余进入知识库', recommendedTemplateItems(items), attendance, recommendedKnowledgeItems(items))
    }
    if (/(全部|所有|这批).*(入库|同步|写入).*(数据库|业务库|对应库)/.test(normalized)) {
      return makeBatchPlan('高置信资料写入对应库，并保留知识和真实模板', recommendedTemplateItems(items), recommendedDatabaseItems(items), recommendedKnowledgeItems(items))
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
    return `知识库 ${plan.knowledgeItemIds.length} 个；模板库 ${plan.templateItemIds.length} 个；${databaseText}`
  }

  async function executeBatchPlan(plan: OfficeDockingBatchPlan): Promise<void> {
    const items = readyBatchItems()
    for (const item of items) {
      item.selectedTemplate = plan.templateItemIds.includes(item.id)
      item.selectedDatabase = plan.databaseItemIds.includes(item.id)
      item.selectedKnowledge = plan.knowledgeItemIds.includes(item.id)
      if (!item.selectedTemplate && !item.selectedDatabase && !item.selectedKnowledge) {
        item.commitStatus = 'skipped'
        continue
      }
      await executeOfficeDockingItem(item)
    }
    touchItems()
  }

  function executionTargetDetails(item: ChatOfficeDockingReviewItem): string[] {
    const details: string[] = []
    if (item.selectedTemplate) {
      if (item.templateCommitStatus === 'committed') details.push('模板库成功')
      else if (item.templateCommitStatus === 'rolled_back') details.push('模板库已自动回滚')
      else if (item.templateCommitStatus === 'failed') details.push(`模板库失败（${item.templateError || item.error || '未知原因'}）`)
      else details.push('模板库未执行')
    }
    if (item.selectedDatabase) {
      const target = item.databaseTargetLabel || '业务数据库'
      if (item.databaseCommitStatus === 'committed') details.push(`${target}成功`)
      else if (item.databaseCommitStatus === 'rolled_back') details.push(`${target}已自动回滚`)
      else if (item.databaseCommitStatus === 'failed') details.push(`${target}失败（${item.databaseError || item.error || '未知原因'}）`)
      else details.push(`${target}未执行${item.templateError ? '（模板归档先失败）' : ''}`)
    }
    if (item.selectedKnowledge) {
      if (item.knowledgeCommitStatus === 'committed') details.push('知识库成功')
      else if (item.knowledgeCommitStatus === 'rolled_back') details.push('知识库已自动回滚')
      else if (item.knowledgeCommitStatus === 'failed') details.push(`知识库失败（${item.knowledgeError || item.error || '未知原因'}）`)
      else details.push('知识库未执行')
    }
    if (item.rollbackError) details.push(`模板自动回滚失败（${item.rollbackError}）`)
    return details
  }

  function batchExecutionReceipt(items: ChatOfficeDockingReviewItem[]): string {
    const committed = items.filter((item) => item.commitStatus === 'committed')
    const partial = items.filter((item) => item.commitStatus === 'partial')
    const failed = items.filter((item) => item.commitStatus === 'failed')
    const skipped = items.filter((item) => item.commitStatus === 'skipped')
    const lines = items.map((item, index) => {
      if (item.commitStatus === 'skipped') return `${index + 1}. ${item.fileName}：未处理`
      const state = item.commitStatus === 'committed' ? '完整成功' : item.commitStatus === 'partial' ? '部分成功' : '失败'
      const details = executionTargetDetails(item)
      return `${index + 1}. ${item.fileName}：${state}${details.length ? `；${details.join('；')}` : ''}`
    })
    return [
      `这批文件执行完成：完整成功 ${committed.length} 个，部分成功 ${partial.length} 个，失败 ${failed.length} 个，未处理 ${skipped.length} 个。`,
      '',
      '逐项结果：',
      ...lines,
      ...(partial.length || failed.length
        ? ['', '失败项没有被标记为成功；已回滚的模板可安全重试，部分成功项会保留已成功目标并只重试失败目标。']
        : []),
    ].join('\n')
  }

  async function handleOfficeDockingConversationDecision(message: string): Promise<boolean> {
    if (mode !== 'conversation' || !officeDockingAwaitingDecision.value) return false
    const normalized = String(message || '').replace(/\s+/g, '')
    if (/^确认执行[。！!]*$/.test(normalized)) {
      await deps.addAndSaveMessage(message, 'user')
      const plan = officeDockingBatchPlan.value
      if (!plan) {
        await deps.addAndSaveMessage('还没有形成明确的整批处理方案。请先告诉我想怎么处理，例如“按建议处理”或“全部只进入知识库”。', 'ai')
        return true
      }
      await deps.addAndSaveMessage(`收到，开始执行“${plan.label}”。`, 'ai')
      await executeBatchPlan(plan)
      const failed = officeDockingReviewItems.value.filter((item) => item.commitStatus === 'failed')
      const partial = officeDockingReviewItems.value.filter((item) => item.commitStatus === 'partial')
      officeDockingAwaitingDecision.value = failed.length > 0 || partial.length > 0
      officeDockingBatchPlan.value = null
      await deps.addAndSaveMessage(batchExecutionReceipt(officeDockingReviewItems.value), 'ai')
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
      await deps.addAndSaveMessage(
        '好的，这批文件先不处理。没有写入知识库、数据库或模板库。以后需要时可以重新上传或继续告诉我处理方案。',
        'ai',
      )
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
    stopOfficeDockingClock()
    officeDockingPanelOpen.value = false
    officeDockingReviewItems.value = []
    officeDockingAwaitingDecision.value = false
    officeDockingBatchPlan.value = null
    officeDockingProgressPhase.value = 'idle'
    officeDockingProgressSourceLabel.value = ''
    officeDockingProgressTotal.value = 0
    officeDockingProgressCurrentIndex.value = 0
    officeDockingProgressCurrentFile.value = ''
    officeDockingProgressIgnored.value = []
    officeDockingCancelRequested.value = false
  }

  return {
    officeDockingInputRef,
    officeDockingFolderInputRef,
    officeDockingProcessing,
    officeDockingPanelOpen,
    officeDockingReviewItems,
    officeDockingPendingCount,
    officeDockingAwaitingDecision,
    officeDockingProgress,
    triggerOfficeDocking,
    triggerOfficeDockingFolder,
    cancelOfficeDockingReading,
    onOfficeDockingFileChange,
    toggleOfficeDockingTarget,
    updateOfficeDockingTemplateName,
    confirmOfficeDockingReview,
    skipCurrentOfficeDockingReview,
    handleOfficeDockingConversationDecision,
    clearOfficeDockingReview,
  }
}

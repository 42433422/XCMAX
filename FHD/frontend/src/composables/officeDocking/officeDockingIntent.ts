/**
 * 办公对接意图识别（拆分自 composables/useChatOfficeDocking.ts，行为保持一致）：
 * 表格/文件字段启发式判断业务意图，并支持送货单 ETL 预览回填。
 */
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import { extractFieldNames } from './officeDockingShared'
import type {
  ChatOfficeDockingReviewItem,
  OfficeDockingDatabaseAction,
  OfficeDockingIntentId,
  ShipmentEtlNotePreview,
  ShipmentEtlPreview,
} from './officeDockingShared'

export function compactText(value: unknown): string {
  return String(value || '')
    .replace(/\s+/g, '')
    .trim()
}

export function excelSheetNames(analysis?: Record<string, unknown>): string[] {
  const preview = asRecord(analysis?.preview_data)
  const fromPreview = asArray<unknown>(preview.sheet_names)
    .map((name) => asString(name).trim())
    .filter(Boolean)
  const fromSheets = asArray<Record<string, unknown>>(analysis?.sheets)
    .map((sheet) => asString(sheet.sheet_name || sheet.name).trim())
    .filter(Boolean)
  return [...new Set([...fromPreview, ...fromSheets])]
}

export function allFieldNames(analysis?: Record<string, unknown>): string[] {
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

export function inferOfficeDockingIntent(item: {
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
    intentSummary: '已读取表格，但业务目标不明确；先进入知识库，避免误写数据库',
    databaseTargetLabel: '',
    databaseAction: '',
    databaseDisabledReason: '未识别到明确的业务库目标',
    selectedDatabase: false,
  }
}

export function applyShipmentEtlIntent(item: ChatOfficeDockingReviewItem, preview: ShipmentEtlPreview): void {
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

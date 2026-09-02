/**
 * 办公对接共享类型、标签与纯函数（拆分自 composables/useChatOfficeDocking.ts，行为保持一致）。
 */
import {
  CSV_FULL_READ_EMPLOYEE_ID,
  EXCEL_FULL_READ_EMPLOYEE_ID,
  PDF_FULL_READ_EMPLOYEE_ID,
  PPT_FULL_READ_EMPLOYEE_ID,
  WORD_FULL_READ_EMPLOYEE_ID,
} from '@/constants/officeEmployeePack'
import type { OfficeEmployeeOutputFile, OfficeFileUploadResult } from '@/utils/officeEmployeeReadApi'
import { asArray, asRecord, asString } from '@/utils/typeGuards'

export type OfficeDockingTarget = 'knowledge' | 'database'
export type OfficeDockingStatus = 'running' | 'ready' | 'error'
export type OfficeDockingCommitStatus = '' | 'committing' | 'committed' | 'failed'
export type OfficeDockingIntentId =
  | 'pending'
  | 'attendance_roster'
  | 'attendance_source'
  | 'shipment_delivery'
  | 'customer_product'
  | 'generic_table'
  | 'document'
export type OfficeDockingDatabaseAction = '' | 'attendance_import' | 'shipment_etl_execute' | 'customer_product_import'

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
}

export const EMPLOYEE_LABELS: Record<string, string> = {
  [EXCEL_FULL_READ_EMPLOYEE_ID]: 'Excel 读取员',
  [CSV_FULL_READ_EMPLOYEE_ID]: 'CSV 全量读取员',
  [PDF_FULL_READ_EMPLOYEE_ID]: 'PDF 全量读取员',
  [PPT_FULL_READ_EMPLOYEE_ID]: 'PPT 全量读取员',
  [WORD_FULL_READ_EMPLOYEE_ID]: 'Word 全量读取员',
}

export const KIND_LABELS: Record<string, string> = {
  [EXCEL_FULL_READ_EMPLOYEE_ID]: 'Excel',
  [CSV_FULL_READ_EMPLOYEE_ID]: 'CSV',
  [PDF_FULL_READ_EMPLOYEE_ID]: 'PDF',
  [PPT_FULL_READ_EMPLOYEE_ID]: 'PPT',
  [WORD_FULL_READ_EMPLOYEE_ID]: 'Word',
}

export function newItemId(): string {
  return `office-docking-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

export function outputRelpathFor(itemId: string, employeeId: string): string {
  if (employeeId === PDF_FULL_READ_EMPLOYEE_ID) return `outputs/chat-docking/${itemId}/document_full.txt`
  if (employeeId === WORD_FULL_READ_EMPLOYEE_ID) return `outputs/chat-docking/${itemId}/document_full.json`
  if (employeeId === PPT_FULL_READ_EMPLOYEE_ID) return `outputs/chat-docking/${itemId}/presentation_full.json`
  if (employeeId === CSV_FULL_READ_EMPLOYEE_ID) return `outputs/chat-docking/${itemId}/data.json`
  return `outputs/chat-docking/${itemId}/workbook.json`
}

export function collectEmployeeOutputPaths(employeeData: Record<string, unknown>): string[] {
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

export function firstJsonData(outputs: OfficeEmployeeOutputFile[]): Record<string, unknown> {
  const found = outputs.find((f) => f.kind === 'json' && f.json && typeof f.json === 'object')
  return asRecord(found?.json)
}

export function firstText(outputs: OfficeEmployeeOutputFile[]): string {
  return asString(outputs.find((f) => f.kind === 'text' && f.text)?.text).trim()
}

export function truncate(text: string, max = 6000): string {
  const raw = String(text || '').trim()
  return raw.length > max ? `${raw.slice(0, max)}\n...` : raw
}

export function stringifyPreview(value: unknown, max = 6000): string {
  try {
    return truncate(JSON.stringify(value, null, 2), max)
  } catch {
    return truncate(String(value || ''), max)
  }
}

export function extractFieldNames(analysis?: Record<string, unknown>): string[] {
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

export function extractSampleRows(analysis?: Record<string, unknown>): Record<string, unknown>[] {
  const preview = asRecord(analysis?.preview_data)
  return asArray<Record<string, unknown>>(preview.sample_rows)
    .map((row) => asRecord(row))
    .slice(0, 8)
}

/**
 * 办公对接审核条目。解析和入库走 ELT，工作表模板可选。
 */
import type { OfficeEmployeeOutputFile, OfficeFileUploadResult } from '@/utils/officeEmployeeReadApi'

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
  worksheetTemplates?: { id: string; label: string; sheet: string }[]
  selectedTemplateIndex?: number
  pipeline?: string
}

export interface UseChatOfficeDockingDeps {
  addAndSaveMessage: (content: string, role?: 'user' | 'ai' | 'task', extras?: Record<string, unknown>) => Promise<void>
  stageExcelAnalysisContext: (payload: Record<string, unknown>) => void
  sendDatabaseImportMessage: (message: string) => Promise<void>
}

export function newItemId(): string {
  return `office-docking-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

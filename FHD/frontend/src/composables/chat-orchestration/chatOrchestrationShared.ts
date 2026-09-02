/**
 * useChatOrchestration 拆出的共享类型与纯工具函数（行为零变更）。
 */
import type { ChatAutoAction, ChatPlannerPayload } from '@/types/chat'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import type { useChatMessages } from '../useChatMessages'
import type { ShipmentTask } from '../useShipmentTask'

/** 与 useChatOrchestration 内 tts 包装后的 addAndSaveMessage 签名一致 */
export type ChatOrchestrationAddAndSaveMessage = (
  content: string,
  role?: 'user' | 'ai' | 'task',
  extras?: Parameters<ReturnType<typeof useChatMessages>['addAndSaveMessage']>[2],
  targetSessionId?: string,
) => Promise<void>

export type XcagiChatWindow = Window & {
  __VUE_CHAT_FILL__?: (value: string) => boolean
  legacyAutoActionHandler?: (action: ChatAutoAction, userMessage: string) => void
}
export type DynamicShipmentTask = ShipmentTask & Record<string, unknown>

export function getXcagiWindow(): XcagiChatWindow {
  return window as XcagiChatWindow
}

export function asShipmentTask(value: unknown): DynamicShipmentTask {
  const row = asRecord(value)
  return {
    ...row,
    type: asString(row.type),
  } as DynamicShipmentTask
}

export function asPlannerPayload(value: unknown): ChatPlannerPayload {
  return asRecord(value) as ChatPlannerPayload
}

export function asAutoAction(value: unknown): ChatAutoAction {
  return asRecord(value) as ChatAutoAction
}

export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : asString(err, fallback)
}

export function generateSessionId(): string {
  return Date.now().toString(36) + Math.random().toString(36).substr(2)
}

export function normalizeServerContentToHtml(raw: unknown): string {
  const text = String(raw || '')
  if (/<[a-z][\s\S]*>/i.test(text)) return text
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML.replace(/\n/g, '<br>')
}

export function buildTaskCompletedDescription(successMsg: string, data: unknown): string {
  const row = asRecord(data)
  const nestedData = asRecord(row.data)
  const document = asRecord(row.document || nestedData.document)
  const parts = [successMsg || '任务执行成功']
  const docName = row.doc_name || nestedData.doc_name || document.filename
  const orderNo = row.order_number || nestedData.order_number || document.order_number
  const filePath = row.file_path || nestedData.file_path || document.filepath
  const labels = asArray(row.labels).length ? asArray(row.labels) : asArray(nestedData.labels)
  if (docName) parts.push(`文档：${docName}`)
  if (orderNo) parts.push(`单号：${orderNo}`)
  if (typeof row.record_id !== 'undefined' && row.record_id !== null) parts.push(`记录ID：${row.record_id}`)
  if (typeof row.order_id !== 'undefined' && row.order_id !== null) parts.push(`订单ID：${row.order_id}`)
  if (labels.length) parts.push(`标签：${labels.length} 张`)
  if (filePath) parts.push(`路径：${filePath}`)
  return parts.join('；')
}

export function buildShipmentDownloadUrl(data: unknown): string {
  const row = asRecord(data)
  const nestedData = asRecord(row.data)
  const document = asRecord(row.document || nestedData.document)
  const directUrl = row.download_url || nestedData.download_url
  if (directUrl && typeof directUrl === 'string') return directUrl

  const docName = row.doc_name || nestedData.doc_name || document.filename
  if (!docName || typeof docName !== 'string') return ''

  return `/api/shipment/download/${encodeURIComponent(docName)}`
}

export function normalizeRecordId(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  const normalized = Math.trunc(n)
  return normalized > 0 ? normalized : null
}

export function extractShipmentExecutionContext(data: unknown) {
  const row = asRecord(data)
  const nestedData = asRecord(row.data)
  const document = asRecord(row.document || nestedData.document)
  const filePath = asString(row.file_path || nestedData.file_path || document.filepath)
  const purchaseUnit = String(row.purchase_unit ?? nestedData.purchase_unit ?? document.purchase_unit ?? '').trim()
  const orderId = normalizeRecordId(
    row.order_id ?? row.record_id ?? nestedData.order_id ?? nestedData.record_id ?? document.order_id ?? document.record_id,
  )
  const labelsRaw = asArray(row.labels).length ? asArray(row.labels) : asArray(nestedData.labels)

  const labelPaths: string[] = []
  labelsRaw.forEach((label: unknown) => {
    if (typeof label === 'string' && label.trim()) {
      labelPaths.push(label.trim())
      return
    }
    if (label && typeof label === 'object') {
      const labelRow = asRecord(label)
      const p = labelRow.file_path || labelRow.path || labelRow.filePath || labelRow.filepath || ''
      if (typeof p === 'string' && p.trim()) {
        labelPaths.push(p.trim())
      }
    }
  })

  return {
    filePath,
    purchaseUnit,
    orderId,
    labelPaths: Array.from(new Set(labelPaths)),
  }
}

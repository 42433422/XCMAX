/**
 * AI 客服视图共享类型（原单文件机械迁出）。
 */
import type { UnknownRecord } from '../../utils/typeNarrowing'

export interface CustomerTicket extends UnknownRecord {
  id: number | string
  intent?: unknown
  status?: unknown
  title?: unknown
}

export type UiMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  cards?: UnknownRecord[]
  imageDataUrl?: string | null
}

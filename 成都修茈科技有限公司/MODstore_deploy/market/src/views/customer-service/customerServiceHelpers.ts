/**
 * 工单卡片展示辅助（原单文件机械迁出，逐字保留）。
 */
import { ticketIntentLabel } from '../../utils/csTicketLifecycle'
import type { CustomerTicket } from './customerServiceTypes'

export function shortLifeLabel(label: string) {
  const map: Record<string, string> = {
    已收到: '收到',
    处理中: '处理',
    有结果: '结果',
    待补充: '补充',
    已完成: '完成',
    工单排队: '收到',
    工单处理: '处理',
    结果汇报: '结果',
    继续提交: '补充',
    结果回访: '完成',
  }
  return map[label] || label
}

export function friendlyTicketTitle(ticket: CustomerTicket) {
  const intent = ticketIntentLabel(ticket?.intent)
  const title = String(ticket?.title || '').trim()
  if (title && !title.includes('CS') && title.length <= 18) return title
  return intent === '咨询' ? '咨询跟进' : `${intent}跟进`
}

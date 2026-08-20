/** 用户侧工单五阶段进度（与后端 ticket_lifecycle_stage 对齐） */

export type TicketLifecycleStep = {
  stage: number
  label: string
  state: 'done' | 'current' | 'todo'
}

export const TICKET_LIFECYCLE_STEPS: ReadonlyArray<{ stage: number; label: string }> = [
  { stage: 1, label: '已收到' },
  { stage: 2, label: '处理中' },
  { stage: 3, label: '有结果' },
  { stage: 4, label: '待补充' },
  { stage: 5, label: '已完成' },
] as const

/** 兼容旧文案 → 新口语 */
const LABEL_ALIASES: Record<string, string> = {
  工单排队: '已收到',
  工单处理: '处理中',
  结果汇报: '有结果',
  继续提交: '待补充',
  结果回访: '已完成',
}

export function resolveTicketLifecycleStage(ticket: { lifecycle_stage?: unknown; status?: unknown; decision_status?: unknown }): number {
  const fromApi = Number(ticket?.lifecycle_stage || 0)
  if (fromApi >= 1 && fromApi <= 5) return fromApi

  const s = String(ticket?.status || '').toLowerCase()
  const d = String(ticket?.decision_status || '').toLowerCase()
  if (['resolved', 'closed', 'done', 'rejected'].includes(s)) return 5
  if (s === 'waiting_user' || d === 'needs_more_info') return 4
  if (['open', 'pending', 'queued'].includes(s)) return 1
  if (s === 'processing') {
    if (d === 'approved' || d === 'rejected') return 3
    return 2
  }
  if (d === 'approved' || d === 'rejected') return 3
  return 1
}

export function ticketLifecycleLabel(ticket: {
  lifecycle_label?: unknown
  lifecycle_stage?: unknown
  status?: unknown
  decision_status?: unknown
}): string {
  const fromApi = String(ticket?.lifecycle_label || '').trim()
  if (fromApi) return LABEL_ALIASES[fromApi] || fromApi
  const stage = resolveTicketLifecycleStage(ticket)
  return TICKET_LIFECYCLE_STEPS.find((x) => x.stage === stage)?.label || '已收到'
}

const INTENT_LABELS: Record<string, string> = {
  refund: '退款',
  catalog_complaint: '商品投诉',
  catalog_review: '上架审核',
  account_support: '账号权益',
  llm_extension: '模型扩展',
  product_issue: '功能问题',
  general: '咨询',
  greeting: '咨询',
}

export function ticketIntentLabel(intent: unknown): string {
  const key = String(intent || '')
    .trim()
    .toLowerCase()
  return INTENT_LABELS[key] || (key ? key : '咨询')
}

const ISSUE_DOMAIN_LABELS: Record<string, string> = {
  platform: '平台',
  software: '软件',
  custom: '客户定制',
}

/** 平台 / 市场上架软件 / 账号定制线 */
export function issueDomainLabel(ticketOrDomain: unknown): string {
  if (typeof ticketOrDomain === 'string') {
    const key = ticketOrDomain.trim().toLowerCase()
    return ISSUE_DOMAIN_LABELS[key] || ''
  }
  const t = (ticketOrDomain || {}) as {
    issue_domain?: unknown
    issue_domain_label?: unknown
    evidence?: { issue_domain?: unknown; issue_domain_label?: unknown }
    title?: unknown
  }
  const fromApi = String(t.issue_domain_label || t.evidence?.issue_domain_label || '').trim()
  if (fromApi) return fromApi
  const key = String(t.issue_domain || t.evidence?.issue_domain || '')
    .trim()
    .toLowerCase()
  if (ISSUE_DOMAIN_LABELS[key]) return ISSUE_DOMAIN_LABELS[key]
  const title = String(t.title || '')
  if (title.includes('定制')) return '客户定制'
  if (title.includes('软件')) return '软件'
  if (title.includes('平台功能')) return '平台'
  return ''
}

export function ticketLifecycleHint(ticket: {
  lifecycle_stage?: unknown
  status?: unknown
  decision_status?: unknown
  summary?: unknown
}): string {
  const stage = resolveTicketLifecycleStage(ticket)
  if (stage === 1) return '已收到，正在安排'
  if (stage === 2) return '正在为你处理'
  if (stage === 3) return '可以查看处理结果'
  if (stage === 4) return '还差一些信息，点开后在对话里补充'
  if (stage === 5) return '已处理完成'
  return ''
}

export function ticketLifecycleSteps(ticket: {
  lifecycle_steps?: unknown
  lifecycle_stage?: unknown
  status?: unknown
  decision_status?: unknown
}): TicketLifecycleStep[] {
  const current = resolveTicketLifecycleStage(ticket)
  // 始终用口语标签，避免旧 API 文案把用户搞晕
  return TICKET_LIFECYCLE_STEPS.map((step) => ({
    stage: step.stage,
    label: step.label,
    state: step.stage < current ? 'done' : step.stage === current ? 'current' : 'todo',
  }))
}

export function shortTicketRef(ticket: { subject_id?: unknown; ticket_no?: unknown; intent?: unknown }): string {
  const subject = String(ticket?.subject_id || '').trim()
  if (subject) return subject.length > 16 ? `${subject.slice(0, 14)}…` : subject
  const no = String(ticket?.ticket_no || '').trim()
  if (no.length > 10) return `编号 ${no.slice(-6)}`
  return no || ticketIntentLabel(ticket?.intent)
}

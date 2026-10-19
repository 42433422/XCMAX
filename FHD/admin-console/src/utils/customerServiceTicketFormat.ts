/**
 * 客服工单展示层：中文标签、北京时间、状态徽标色和处理时间线。
 * 只做展示转换，不改变任何工单数据；未登记的 key 原样显示，避免把未知状态“翻译”成错误含义。
 */
export type Row = Record<string, unknown>
export type Tone = 'success' | 'info' | 'warning' | 'danger' | 'neutral'
export type Badge = { label: string; tone: Tone; raw: string }

const TIME_FORMAT = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
})

/** 服务端时间列按 UTC 落库，序列化时不带时区；无时区后缀一律按 UTC 解析，再转北京时间。 */
export function parseServerTime(value: unknown): number | null {
  const text = String(value ?? '').trim()
  if (!text) return null
  const iso = text.replace(' ', 'T')
  const zoned = /(Z|[+-]\d{2}:?\d{2})$/i.test(iso) ? iso : `${iso}Z`
  const ms = Date.parse(zoned)
  return Number.isFinite(ms) ? ms : null
}

export function formatBeijingTime(value: unknown, empty = '—'): string {
  const ms = parseServerTime(value)
  if (ms === null) return String(value ?? '').trim() || empty
  const parts = Object.fromEntries(TIME_FORMAT.formatToParts(new Date(ms)).map(p => [p.type, p.value]))
  const hour = parts.hour === '24' ? '00' : parts.hour
  return `${parts.year}-${parts.month}-${parts.day} ${hour}:${parts.minute}:${parts.second}`
}

type LabelMap = Record<string, [string, Tone]>
const badgeFrom = (map: LabelMap, value: unknown, fallbackTone: Tone = 'neutral'): Badge => {
  const raw = String(value ?? '').trim()
  const hit = map[raw.toLowerCase()]
  return hit ? { label: hit[0], tone: hit[1], raw } : { label: raw || '未记录', tone: fallbackTone, raw }
}

const TICKET_STATUS: LabelMap = {
  open: ['待处理', 'info'], new: ['待处理', 'info'], pending: ['待处理', 'info'],
  processing: ['处理中', 'info'], in_progress: ['处理中', 'info'],
  awaiting_customer: ['待客户确认', 'warning'], waiting_customer: ['待客户确认', 'warning'],
  reopened: ['已重新打开', 'warning'], resolved: ['已完成', 'success'],
  closed: ['已关闭', 'neutral'], rejected: ['已拒绝', 'danger'], cancelled: ['已取消', 'neutral'],
}
const LIFECYCLE_TONE: Record<string, Tone> = { 已收到: 'info', 处理中: 'info', 有结果: 'warning', 待补充: 'warning', 已完成: 'success' }

/** 状态徽标：优先使用服务端给出的生命周期中文名，英文原值只放在 title 里供排查。 */
export function ticketStatusBadge(ticket: Row): Badge {
  const base = badgeFrom(TICKET_STATUS, ticket.status)
  const life = String(ticket.lifecycle_label || '').trim()
  if (!life) return base
  return { label: life, tone: base.raw in TICKET_STATUS ? base.tone : LIFECYCLE_TONE[life] || 'neutral', raw: base.raw }
}

const RUN_STATUS: LabelMap = {
  pending: ['待执行', 'neutral'], queued: ['排队中', 'neutral'], running: ['执行中', 'info'],
  completed: ['已完成', 'success'], succeeded: ['成功', 'success'], success: ['成功', 'success'], ok: ['成功', 'success'],
  failed: ['失败', 'danger'], error: ['失败', 'danger'], skipped: ['已跳过', 'neutral'],
  blocked: ['已阻断', 'danger'], cancelled: ['已取消', 'neutral'], unknown: ['未知', 'warning'],
}
export const runStatusBadge = (value: unknown) => badgeFrom(RUN_STATUS, value, 'warning')

const RESOLUTION_STATE: LabelMap = {
  received: ['已收到', 'info'], processing: ['处理中', 'info'], repairing: ['修复中', 'info'],
  repair_failed: ['修复未完成', 'danger'], repaired: ['已修复待验证', 'warning'],
  awaiting_verification: ['待客户验证', 'warning'], verified: ['已验证', 'success'],
  resolved: ['客户确认已解决', 'success'], reopened: ['已重新打开', 'warning'], closed: ['已关闭', 'neutral'],
}
export const resolutionStateBadge = (value: unknown) => badgeFrom(RESOLUTION_STATE, value, 'warning')

const DECISION: LabelMap = {
  accepted: ['已受理', 'info'], approved: ['已批准', 'success'], rejected: ['已拒绝', 'danger'],
  needs_clarification: ['需补充信息', 'warning'], clarify: ['需补充信息', 'warning'],
  escalated: ['已升级人工', 'warning'], auto_resolved: ['自动办结', 'success'], held: ['暂缓', 'neutral'],
}
export const decisionBadge = (value: unknown) => badgeFrom(DECISION, value, 'info')

const RISK: LabelMap = { low: ['低风险', 'success'], medium: ['中风险', 'warning'], high: ['高风险', 'danger'], critical: ['严重风险', 'danger'] }
export const riskBadge = (value: unknown) => badgeFrom(RISK, value)

export const yesNoBadge = (value: unknown, yes: string, no: string): Badge =>
  value === true ? { label: yes, tone: 'success', raw: 'true' }
    : value === false ? { label: no, tone: 'danger', raw: 'false' }
      : { label: '未记录', tone: 'neutral', raw: '' }

const plain = (map: Record<string, string>) => (value: unknown) => {
  const raw = String(value ?? '').trim()
  return map[raw.toLowerCase()] || raw || '未记录'
}
export const intentLabel = plain({
  greeting: '问候', general: '一般咨询', product_issue: '产品问题', refund: '退款',
  catalog_complaint: '商品投诉', catalog_review: '商品评价', account_support: '账号支持', llm_extension: '模型扩展',
})
export const submitterTypeLabel = plain({
  admin: '管理员提交', customer: '客户提交', unknown: '提交人待确认',
})
export const priorityLabel = plain({ low: '低', normal: '普通', high: '高', urgent: '紧急' })
export const roleLabel = plain({ scout: '排查', fix: '修复', verify: '验证' })
export const actorLabel = plain({ ai: 'AI 客服', system: '系统', user: '客户', customer: '客户', admin: '管理员', employee: '数字员工' })
export const routeLabel = plain({ shared_core: '平台公共修复', custom: '客户定制修复', software: '软件修复' })
export const actionTypeLabel = plain({ 'employee.dispatch': '派单给处理小组', 'ticket.reply': '回复客户', 'ticket.close': '关闭工单' })
export const eventLabel = plain({
  ticket_title_corrected: '更正工单标题',
  ticket_created: '创建工单', decision_made: 'AI 受理决策', employee_progress: '员工处理进展',
  action_executed: '执行动作', action_forbidden: '动作被拒绝', session_created: '创建会话',
  chat_only_reply: '仅对话回复', issue_intake: '问题受理', issue_support_report: '上传支持包',
  customer_issue_resolved: '客户确认已解决', customer_issue_reopen: '客户重新打开',
  forbidden_request_refused: '拒绝越权请求', event_enqueue_failed: '事件入队失败',
  content_blocked: '内容被拦截', rate_limited: '请求过于频繁',
})

const asRows = (value: unknown): Row[] => Array.isArray(value) ? value.filter((v): v is Row => !!v && typeof v === 'object') : []
const clip = (value: unknown, max = 240) => {
  const text = String(value ?? '').trim()
  return text.length > max ? `${text.slice(0, max)}…` : text
}

export type TeamMember = { role: string; employee: string; status: Badge; ok: Badge }
export function teamMembers(value: unknown): TeamMember[] {
  return asRows(value).map(m => ({
    role: roleLabel(m.role), employee: String(m.employee_id || '未记录'),
    status: runStatusBadge(m.status), ok: yesNoBadge(m.ok, '成功', '未成功'),
  }))
}

export type TimelineItem = {
  key: string; at: unknown; sort: number; kind: string; title: string
  badges: Badge[]; text: string; team: TeamMember[]; raw: unknown
}

/** 把决策、执行动作、员工回写和客户确认合成一条按时间排序的处理时间线。 */
export function buildTimeline(decisions: Row[], actions: Row[], evidence: Row): TimelineItem[] {
  const items: TimelineItem[] = []
  const push = (item: Omit<TimelineItem, 'sort'>) => items.push({ ...item, sort: parseServerTime(item.at) ?? Number.MAX_SAFE_INTEGER })
  for (const d of decisions) {
    const confidence = Number(d.confidence)
    push({
      key: `decision-${d.id}`, at: d.created_at, kind: '决策', title: `决策 #${d.id ?? '—'} · ${intentLabel(d.intent)}`,
      badges: [decisionBadge(d.decision), riskBadge(d.risk_level), ...(Number.isFinite(confidence) && d.confidence !== null && d.confidence !== '' ? [{ label: `置信度 ${Math.round(confidence * 100)}%`, tone: 'neutral' as Tone, raw: String(d.confidence) }] : [])],
      text: clip(d.rationale), team: [], raw: d,
    })
  }
  for (const a of actions) {
    const request = (a.request && typeof a.request === 'object' ? a.request : {}) as Row
    push({
      key: `action-${a.id}`, at: a.created_at, kind: '执行动作', title: `动作 #${a.id ?? '—'} · ${actionTypeLabel(a.action_type)}`,
      badges: [runStatusBadge(a.status), ...('team_ok' in request ? [yesNoBadge(request.team_ok, '小组处理成功', '小组处理未成功')] : [])],
      text: clip(a.error || (a.target_id ? `目标：${a.target_type || ''} ${a.target_id}` : '')),
      team: teamMembers(request.roles), raw: a,
    })
  }
  asRows(evidence.employee_reports).forEach((r, i) => push({
    key: `report-${i}`, at: r.at, kind: '员工回写', title: '员工处理进展',
    badges: [yesNoBadge(r.team_ok, '小组处理成功', '小组处理未成功')], text: clip(r.progress), team: [], raw: r,
  }))
  asRows(evidence.customer_decisions).forEach((c, i) => push({
    key: `customer-${i}`, at: c.at, kind: '客户确认', title: c.decision === 'reopen' ? '客户重新打开工单' : c.decision === 'resolved' ? '客户确认已解决' : `客户操作：${c.decision ?? '未记录'}`,
    badges: [c.decision === 'reopen' ? { label: '重新打开', tone: 'warning', raw: 'reopen' } : { label: '已确认', tone: 'success', raw: String(c.decision ?? '') }],
    text: '', team: [], raw: c,
  }))
  return items.sort((a, b) => a.sort - b.sort)
}

export type AuditItem = { key: string; id: string; at: string; actor: string; event: string; eventKey: string; summary: string; raw: unknown }
export function auditItems(rows: Row[]): AuditItem[] {
  return rows.map((row, i) => {
    const detail = (row.detail && typeof row.detail === 'object' ? row.detail : row.detail_json && typeof row.detail_json === 'object' ? row.detail_json : {}) as Row
    const actorId = row.actor_user_id ?? row.user_id
    const summary = detail.progress || detail.note || detail.reason || (detail.new_title ? `标题：${detail.old_title ?? '（空）'} → ${detail.new_title}` : '') || (detail.decision ? `决策：${decisionBadge(detail.decision).label}` : '') || (detail.intent ? `意图：${intentLabel(detail.intent)}` : '')
    return {
      key: `audit-${row.id ?? i}`, id: String(row.id ?? '—'), at: formatBeijingTime(row.created_at),
      actor: `${actorLabel(row.actor_type)}${actorId !== null && actorId !== undefined && actorId !== '' ? ` · 用户 ID ${actorId}` : ''}`,
      event: eventLabel(row.event_type), eventKey: String(row.event_type ?? ''), summary: clip(summary), raw: row,
    }
  })
}

export const prettyJson = (value: unknown) => JSON.stringify(value, null, 2)

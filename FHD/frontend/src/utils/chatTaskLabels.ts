export function formatTaskTime(ts: number): string {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

/**
 * 会话消息可能来自本地缓存（只有 HH:mm）或服务端（ISO timestamp）。
 * 优先保留原始时刻，只有缺失/非法时才回退到当前时间。
 */
export function formatChatMessageTime(raw: unknown, fallbackNow = Date.now()): string {
  const value = String(raw ?? '').trim()
  if (/^\d{1,2}:\d{2}(?::\d{2})?$/.test(value)) return value.slice(0, 5)
  const parsed = value ? Date.parse(value) : Number.NaN
  const ts = Number.isFinite(parsed) ? parsed : fallbackNow
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

/** 历史会话列表展示日期，避免同名会话只显示时分而无法区分。 */
export function formatHistoryTime(raw: unknown, now = Date.now()): string {
  const ts = Date.parse(String(raw ?? '').trim())
  if (!Number.isFinite(ts)) return ''
  const date = new Date(ts)
  const today = new Date(now)
  const clock = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  if (date.getFullYear() === today.getFullYear() && date.getMonth() === today.getMonth() && date.getDate() === today.getDate()) {
    return `今天 ${clock}`
  }
  if (date.getFullYear() === today.getFullYear()) {
    return `${date.getMonth() + 1}月${date.getDate()}日 ${clock}`
  }
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${clock}`
}

/** 将后端追踪术语转换成面向业务用户的文案。 */
export function normalizeTaskDisplayText(raw: unknown): string {
  return String(raw ?? '')
    .replace(/Legacy\s+planner\s+run/gi, '智能任务')
    .replace(/Legacy\s+planner/gi, '智能任务')
    .replace(/Agent\s+Progress/gi, '执行进度')
    .replace(/Agent\s+run/gi, '智能任务')
    .replace(/Agent\s+计划/gi, '执行计划')
    .replace(/Agent\s+任务/gi, '智能任务')
    .replace(/等待\s*Agent\s*事件/gi, '等待执行状态')
    .replace(/\bAgent\b/gi, '智能执行')
    .replace(/\bplanner\b/gi, '执行计划')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

export function formatTaskSourceLabel(source: string): string {
  const s = String(source || '').trim()
  const map: Record<string, string> = {
    workflow: '工作流',
    excel: 'Excel',
    print: '打印',
    shipment: '发货单',
    manual: '手动',
    system: 'AI 员工',
    wechat: '微信',
    agent: '智能执行',
    pro: 'AI 链路',
    normal: '对话',
  }
  return map[s] || s || '—'
}

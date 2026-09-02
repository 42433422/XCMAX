/**
 * 自进化 loop 面板共用工具（由 SelfEvolutionLoopRuntimePanel.vue 原文机械切分而来）。
 */
export type AnyRecord = Record<string, unknown>

export function asRecord(v: unknown): AnyRecord {
  return v && typeof v === 'object' && !Array.isArray(v) ? v as AnyRecord : {}
}

export function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

export function asString(v: unknown): string {
  return String(v ?? '').trim()
}

export function asNumber(v: unknown, fallback = 0): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

export function firstText(...values: unknown[]): string {
  for (const value of values) {
    const s = asString(value)
    if (s) return s
  }
  return ''
}

const DUTY_ROSTER_VIEW_TOKENS = new Set(['department', 'dept', '六部门', 'hub', 'center', '中心', '中心图', 'legacy-area', 'area', '物理', '物理分区', 'client', 'workshop', '车间', '客户端车间'])

export function normalizeDutyRosterView(raw: unknown): string {
  const token = firstText(raw, '').trim().toLowerCase()
  return DUTY_ROSTER_VIEW_TOKENS.has(token) ? token : 'department'
}

export function governanceSummaryText(row: AnyRecord): string {
  const summary = asRecord(row.onboard_summary)
  const onboarded = Number(summary.onboarded)
  const skipped = Number(summary.skipped)
  const failed = Number(summary.failed)
  if ([onboarded, skipped, failed].every((n) => Number.isFinite(n))) {
    return `onboarded ${onboarded} · skipped ${skipped} · failed ${failed}`
  }
  return firstText(row.status, row.ok === false ? 'failed' : 'success')
}

export function proactiveCandidateTitle(item: AnyRecord): string {
  return firstText(
    item.title,
    item.summary,
    item.reason,
    item.module,
    item.path,
    item.file,
    item.task_type,
    '主动优化候选',
  )
}

export function proactiveCandidateMeta(item: AnyRecord): string {
  return [
    firstText(item.task_type, item.kind, item.category, item.signal_type),
    firstText(item.source, item.script, item.metric),
    item.score != null ? `score ${item.score}` : '',
  ].filter(Boolean).join(' · ') || 'proactive signal'
}

import type { AutonomyGapStatus } from '@/constants/autonomyL4Readiness'
import { asRecord, asString, firstText, type AnyRecord } from './useLoopRuntimePanel'

export const DUTY_ROSTER_VIEW_TOKENS = new Set([
  'department',
  'dept',
  '六部门',
  'hub',
  'center',
  '中心',
  '中心图',
  'legacy-area',
  'area',
  '物理',
  '物理分区',
  'client',
  'workshop',
  '车间',
  '客户端车间',
])

export function normalizeDutyRosterView(raw: unknown): string {
  const token = firstText(raw, '').trim().toLowerCase()
  return DUTY_ROSTER_VIEW_TOKENS.has(token) ? token : 'department'
}

export type EmployeeMention = {
  id: string
  stage: string
  source: string
  rosterLabel?: string
  rosterStatus?: string
  dutyRegisteredLabel?: string
  dutyRegistered?: unknown
  department?: string
}

export function collectEmployeeMentions(value: unknown, out: Map<string, EmployeeMention>, source: string) {
  if (value == null) return
  if (typeof value === 'string') {
    const match = value.match(/\b[a-z][a-z0-9]+(?:-[a-z0-9]+)+\b/g) || []
    for (const id of match) {
      if (!out.has(id)) out.set(id, { id, stage: '提及', source })
    }
    return
  }
  if (Array.isArray(value)) {
    for (const item of value) collectEmployeeMentions(item, out, source)
    return
  }
  if (typeof value !== 'object') return
  const row = value as AnyRecord
  const id = firstText(row.employee_id, row.employeeId, row.emp_id, row.empId, row.actor, row.assignee)
  if (id && id.includes('-')) {
    out.set(id, {
      id,
      stage: firstText(row.step, row.stage, row.role, row.phase, row.status, '循环'),
      source,
    })
  }
  for (const [key, child] of Object.entries(row)) {
    if (key === 'prompt' || key === 'report' || key === 'result' || key === 'steps' || key === 'nodes') {
      collectEmployeeMentions(child, out, source)
    }
  }
}

export function governanceSummaryText(row: AnyRecord): string {
  const summary = asRecord(row.onboard_summary)
  const onboarded = Number(summary.onboarded)
  const skipped = Number(summary.skipped)
  const failed = Number(summary.failed)
  if ([onboarded, skipped, failed].every((n) => Number.isFinite(n))) {
    return `已上岗 ${onboarded} · 跳过 ${skipped} · 失败 ${failed}`
  }
  return firstText(row.status, row.ok === false ? '失败' : '成功')
}

// item.review_dimensions 类型为 unknown，模板中直接 ?.[dimKey] 索引会触发 TS7053。
// 在纯函数中通过 asRecord 收口为 AnyRecord 后再索引，让模板只调函数。
export function reviewDimStatus(item: AnyRecord, dimKey: string): string {
  const dims = asRecord(item.review_dimensions)
  return asString(asRecord(dims[dimKey]).status) || 'n/a'
}

export function reviewDimFailed(item: AnyRecord, dimKey: string): boolean {
  return reviewDimStatus(item, dimKey).toLowerCase() === 'fail'
}

export function gapTone(status: AutonomyGapStatus): string {
  if (status === 'ok') return 'ok'
  if (status === 'partial') return 'warn'
  if (status === 'blocked') return 'bad'
  return 'idle'
}

export function proactiveCandidateTitle(item: Record<string, unknown>): string {
  return firstText(item.title, item.summary, item.reason, item.module, item.path, item.file, item.task_type, '主动优化候选')
}

export function proactiveCandidateMeta(item: Record<string, unknown>): string {
  return (
    [
      firstText(item.task_type, item.kind, item.category, item.signal_type),
      firstText(item.source, item.script, item.metric),
      item.score != null ? `评分 ${item.score}` : '',
    ]
      .filter(Boolean)
      .join(' · ') || '主动信号'
  )
}

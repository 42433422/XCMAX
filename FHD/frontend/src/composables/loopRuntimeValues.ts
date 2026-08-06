import type { Ref } from 'vue'

export type LoopRuntimeConsoleDeps = {
  plannedIds: Ref<ReadonlySet<string>>
  visualizedEmployeeCount: Ref<number>
  totalCount: Ref<number>
  routeFocusedEmployeeId: Ref<string>
  showManagementLoopPanels: Ref<boolean>
}

export function loopRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {}
}

export function loopArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

export function loopString(v: unknown): string {
  return String(v ?? '').trim()
}

export function loopFirstText(...values: unknown[]): string {
  for (const value of values) {
    const text = loopString(value)
    if (text) return text
  }
  return ''
}

export function loopNumber(value: unknown): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

const DUTY_ROSTER_VIEW_TOKENS = new Set(['department', 'dept', '六部门', 'hub', 'center', '中心', '中心图', 'legacy-area', 'area', '物理', '物理分区', 'client', 'workshop', '车间', '客户端车间'])

export function normalizeDutyRosterView(raw: unknown): string {
  const token = String(Array.isArray(raw) ? raw[0] : raw || '').trim().toLowerCase()
  return DUTY_ROSTER_VIEW_TOKENS.has(token) ? token : 'department'
}

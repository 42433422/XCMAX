/** WorkflowView 沙盒域使用的纯函数（自 WorkflowView.vue 原样迁移） */

export function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

export function parsePositiveInt(v: unknown): number {
  const n = parseInt(String(v ?? ''), 10)
  return Number.isFinite(n) && n > 0 ? n : 0
}

export function employeeIdMatches(a: unknown, b: unknown): boolean {
  const x = String(a || '').trim()
  const y = String(b || '').trim()
  if (!x || !y) return false
  if (x === y) return true
  return x.endsWith(`-${y}`) || x.endsWith(`_${y}`) || y.endsWith(`-${x}`) || y.endsWith(`_${x}`)
}

export function workflowEmployeesFromModRow(modRow: unknown): unknown[] {
  const arr = asRecord(modRow).workflow_employees
  return Array.isArray(arr) ? arr : []
}

export function employeeMatchesManifestEntry(entry: unknown, employeeId: unknown, employeeName: string): boolean {
  const record = asRecord(entry)
  const eid = String(record.id || '').trim()
  if (eid && employeeIdMatches(eid, employeeId)) return true
  if (!employeeName) return false
  const label = String(record.label || '').trim()
  const title = String(record.panel_title || '').trim()
  return (
    label === employeeName ||
    title === employeeName ||
    employeeIdMatches(label, employeeId) ||
    employeeIdMatches(title, employeeId)
  )
}

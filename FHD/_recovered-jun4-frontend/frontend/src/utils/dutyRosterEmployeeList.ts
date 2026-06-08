import { ALL_PLANNED_YUANGON_PKG_IDS } from '@/constants/modstoreDutyRosterIds'

export type DutyRosterRowStatus = 'installed' | 'registered' | 'missing' | 'planned'

export type DutyRosterRow = {
  pkgId: string
  status: DutyRosterRowStatus
}

function asIdList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  return raw.map((x) => String(x).trim()).filter(Boolean)
}

/** 由 /api/xcmax/ops/duty-health 或 closure-status 构造编制矩阵行 */
export function buildDutyRosterRows(health: Record<string, unknown>): DutyRosterRow[] {
  const staffing =
    health.staffing && typeof health.staffing === 'object'
      ? (health.staffing as Record<string, unknown>)
      : health
  const missing = new Set(asIdList(staffing.missing_employees ?? health.missing_employees))
  const registered = new Set(
    asIdList(health.registered_employee_ids ?? staffing.registered_employee_ids),
  )
  const planned = new Set(asIdList(health.planned_employee_ids ?? staffing.planned_employee_ids))
  const localCount = Number(health.planned_local_installed_count ?? 0)

  const ids = new Set<string>([...ALL_PLANNED_YUANGON_PKG_IDS, ...missing, ...registered, ...planned])

  return [...ids].sort().map((pkgId) => {
    let status: DutyRosterRowStatus = 'planned'
    if (missing.has(pkgId)) status = 'missing'
    else if (registered.has(pkgId)) status = 'registered'
    else if (planned.has(pkgId) && localCount > 0) status = 'installed'
    return { pkgId, status }
  })
}

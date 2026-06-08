/**
 * 编制矩阵内运维岗（与 duty_roster / AdminDutyEmployeeGraph 编制列表同源）：
 * 仅供工作台等场景判断「MODstore 在岗」编制内员工包，不出现在工作台创作/直连对话列表与 AI 市场。
 */
import { ALL_PLANNED_YUANGON_PKG_IDS } from '../domain/yuangonDutyRoster'

export function isPlannedDutyRosterPkgId(pkgId: string): boolean {
  return ALL_PLANNED_YUANGON_PKG_IDS.has(pkgId)
}

export function filterOutPlannedDutyEmployees<T extends { id?: string }>(rows: T[]): T[] {
  return rows.filter((r) => {
    const id = String(r.id ?? '').trim()
    if (!id) return true
    return !isPlannedDutyRosterPkgId(id)
  })
}

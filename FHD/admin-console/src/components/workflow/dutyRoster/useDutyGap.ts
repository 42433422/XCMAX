import { computed } from 'vue'
import type { DutyRosterState } from './useDutyRosterState'
import type { GapState } from './dutyRosterTypes'
import { ALL_PLANNED_YUANGON_PKG_IDS, YUANGON_PKG_ROLE_LABELS } from '@host/domain/yuangonDutyRoster'
import { ALL_AREAS, isVirtualEmployee } from './dutyRosterConstants'

export function useDutyGap(s: DutyRosterState) {
  const gapRows = computed(() => {
    const rows: Array<{ id: string; name: string; area: string; state: GapState; detail: string }> = []
    const seen = new Set<string>()
    const health = s.rosterHealth.value
    const sameRoster = health?.plannedCount === ALL_PLANNED_YUANGON_PKG_IDS.size
    const areas = [...Object.values(ALL_AREAS), { label: '其它编制岗位', ids: [...ALL_PLANNED_YUANGON_PKG_IDS] }]
    for (const { label, ids } of areas) {
      for (const id of ids) {
        if (seen.has(id) || !ALL_PLANNED_YUANGON_PKG_IDS.has(id)) continue
        seen.add(id)
        const row = s.employees.value.find((employee) => employee.id === id)
        const catalogMissing = health?.catalogKnown && (health.missingCatalogIds.includes(id) || row?.source === 'v1_catalog')
        const localMissing = health?.localKnown && s.missingLocalPackIds.value.has(id)
        const known = sameRoster && health?.catalogKnown && health.localKnown
        const virtual = isVirtualEmployee(id)
        rows.push({
          id, name: row?.name || YUANGON_PKG_ROLE_LABELS[id] || id, area: label,
          state: virtual ? 'deployed' : catalogMissing || localMissing ? 'missing' : known ? 'deployed' : 'unknown',
          detail: virtual ? '前端虚拟岗位，运行另行核对' : [
            catalogMissing ? '目录缺岗' : known ? '目录已登记' : '目录待核实',
            localMissing ? '本端缺包' : known ? '本端包已安装' : '本端安装待核实',
          ].join(' · '),
        })
      }
    }
    for (const id of health?.extraIds || []) {
      if (!seen.has(id)) rows.push({ id, name: YUANGON_PKG_ROLE_LABELS[id] || id, area: '编制外包', state: 'untracked', detail: '已安装但不在当前编制，可按业务需要保留' })
    }
    return rows
  })
  const gapSummary = computed(() => ({
    deployed: gapRows.value.filter((row) => row.state === 'deployed').length,
    missing: gapRows.value.filter((row) => row.state === 'missing').length,
    untracked: gapRows.value.filter((row) => row.state === 'untracked').length,
    unknown: gapRows.value.filter((row) => row.state === 'unknown').length,
  }))
  return { gapRows, gapSummary }
}
export type DutyGap = ReturnType<typeof useDutyGap>

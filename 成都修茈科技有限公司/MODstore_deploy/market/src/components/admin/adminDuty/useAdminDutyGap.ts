/**
 * 缺岗分析（deployed / missing / untracked 分桶）。
 *
 * 由 AdminDutyEmployeeGraph.vue 原文机械迁出。
 */
import { computed } from 'vue'
import { YUANGON_PKG_ROLE_LABELS } from '../../../domain/yuangonDutyRoster'
import { ALL_AREAS, isVirtualEmployee } from './adminDutyConstants'
import type { AdminDutyState } from './useAdminDutyState'
import type { GapState, EmpRow } from './adminDutyTypes'

export function useAdminDutyGap(s: AdminDutyState) {
  const { employees } = s

const gapRows = computed(() => {
  const rows: Array<{ id: string; name: string; area: string; state: GapState }> = []

  for (const [_area, { label, ids }] of Object.entries(ALL_AREAS)) {
    for (const id of ids) {
      const row = employees.value.find((e) => e.id === id)
      const name = row?.name || YUANGON_PKG_ROLE_LABELS[id] || id
      const deployed =
        isVirtualEmployee(id) || row?.source === 'catalog'
      rows.push({
        id,
        name,
        area: label,
        state: deployed ? 'deployed' : 'missing',
      })
    }
  }
  return rows
})


const gapSummary = computed(() => ({
  deployed:  gapRows.value.filter((r) => r.state === 'deployed').length,
  missing:   gapRows.value.filter((r) => r.state === 'missing').length,
  untracked: gapRows.value.filter((r) => r.state === 'untracked').length,
}))


  return { gapRows, gapSummary }
}

export type AdminDutyGap = ReturnType<typeof useAdminDutyGap>

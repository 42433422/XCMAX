import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { normalizeDutyRosterLoopStatus } from '@/composables/useDutyRosterLoopStatus'
import { useDutyRosterState } from '../../../admin-console/src/components/workflow/dutyRoster/useDutyRosterState'
import { useDutyGap } from '../../../admin-console/src/components/workflow/dutyRoster/useDutyGap'
import DutyGapPanel from '../../../admin-console/src/components/workflow/dutyRoster/DutyGapPanel.vue'

vi.mock('@/api/xcmaxMarketProxy', () => ({ default: {} }))
vi.mock('@/domain/yuangonDutyRoster', () => ({ ALL_PLANNED_YUANGON_PKG_IDS: new Set(['e1', 'e2', 'e3', 'e4']), YUANGON_PKG_ROLE_LABELS: { e4: '新增编制岗位' } }))
vi.mock('../../../admin-console/src/components/workflow/dutyRoster/dutyRosterConstants', () => ({
  ALL_AREAS: { a: { label: '部门甲', ids: ['e1', 'e2', 'e3'] }, b: { label: '部门乙', ids: ['e1'] } },
  AREA_COLORS: {}, parseViewModeFromQuery: () => 'department', isDutyGraphMember: () => true, isVirtualEmployee: () => false,
}))

function setup() {
  const state = useDutyRosterState({ query: {} } as RouteLocationNormalizedLoaded)
  state.employees.value = [{ id: 'e1', name: '员工甲', source: 'catalog' }, { id: 'e2', name: '员工乙', source: 'v1_catalog' }, { id: 'e3', name: '员工丙', source: 'catalog' }]
  state.rosterHealth.value = normalizeDutyRosterLoopStatus({ success: true, staffing: { planned_count: 4, missing_employees: ['e2'], missing_local_employee_packs: ['e1'], extra_employees: ['extra-x'] } })
  state.missingLocalPackIds.value = new Set(['e1'])
  return { state, ...useDutyGap(state) }
}

it('distinguishes missing packages, missing catalog entries and extra packages without duplicate employees', () => {
  const { state, gapRows, gapSummary } = setup()
  expect(gapRows.value).toHaveLength(5)
  expect(gapRows.value.find((row) => row.id === 'e4')?.name).toBe('新增编制岗位')
  expect(gapRows.value.find((row) => row.id === 'e1')?.detail).toContain('本端缺包')
  expect(gapRows.value.find((row) => row.id === 'e2')?.detail).toContain('目录缺岗')
  expect(gapSummary.value).toEqual({ deployed: 2, missing: 2, untracked: 1, unknown: 0 })
  expect(state.isDeployedDutyRosterRow(state.employees.value[2])).toBe(true)
  state.rosterHealth.value!.plannedCount = 3
  expect(state.isDeployedDutyRosterRow(state.employees.value[2])).toBe(false)
  expect(gapSummary.value.deployed).toBe(0)
  state.rosterHealth.value = null
  expect(state.isDeployedDutyRosterRow(state.employees.value[2])).toBe(false)
  expect(gapSummary.value).toEqual({ deployed: 0, missing: 0, untracked: 0, unknown: 4 })
})

it('lets customers inspect a missing employee and explains scope and normal handling', async () => {
  const { gapRows, gapSummary } = setup()
  const focusEmployee = vi.fn()
  const wrapper = mount(DutyGapPanel, { props: { showGapPanel: true, gapFocusHint: '', gapRows: gapRows.value, gapSummary: gapSummary.value, focusEmployee } })
  await flushPromises()
  expect(wrapper.text()).toContain('编制外包')
  expect(wrapper.text()).toContain('服务器调度另看运行回执')
  const missing = wrapper.findAll('.dg-gap-row').find((row) => row.text().includes('e1'))!
  await missing.trigger('click')
  expect(focusEmployee).toHaveBeenCalledWith('e1')
  expect(missing.text()).toContain('员工甲')
  expect(wrapper.text()).toContain('核对市场权益和平台')
  wrapper.unmount()
})

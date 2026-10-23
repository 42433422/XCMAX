import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import EmployeeAutonomyView from '../../../admin-console/src/views/EmployeeAutonomyView.vue'
import { xcmaxEmployeeAutonomyApi } from '../../../admin-console/src/api/xcmaxEmployeeAutonomy'

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn(), appPrompt: vi.fn() }))
vi.mock('../../../admin-console/src/api/xcmaxEmployeeAutonomy', () => ({ xcmaxEmployeeAutonomyApi: {
  runtime: async () => ({ ok: false, status: 'degraded', jobs: [], summary: {}, employee_duty_details: {
    never_run_employee_ids: ['test-qa-runner'], approval_required_employee_ids: [],
  } }),
  executionCoverage: async () => ({ planned_count: 2, unproven_employee_ids: ['unknown-employee'] }),
  listSuggestions: async () => ({ items: [{ id: 3, source_employee_id: 'evolution-engine',
    target_employee_ids: ['test-qa-runner', 'site-content-editor'], summary: '核对失败的页面检查', status: 'pending' }] }),
  listQuestions: async () => ({ items: [] }), scorecard: async () => ({ items: [] }),
} }))

it('uses the real suggestion source/target contract and keeps unknown employee identities', async () => {
  const wrapper = mount(EmployeeAutonomyView)
  await flushPromises()
  expect(wrapper.find('.employee-tags').text()).toContain('测试质量运行员')
  expect(wrapper.text()).toContain('unknown-employee')
  await wrapper.findAll('.tabs button')[1].trigger('click')
  const row = wrapper.get('.data-table tbody tr')
  expect(row.text()).toContain('自进化服务')
  expect(row.text()).toContain('测试质量运行员')
  expect(row.text()).toContain('静态站内容编辑员')
  expect(row.text()).toContain('核对失败的页面检查')
  expect(row.text()).toContain('待审批')
  expect(row.text()).not.toContain('—')
  wrapper.unmount()
})


it('replaces an unavailable refresh with unknown state rather than old healthy claims', async () => {
  const wrapper = mount(EmployeeAutonomyView)
  await flushPromises()
  const runtime = vi.spyOn(xcmaxEmployeeAutonomyApi, 'runtime').mockRejectedValue(new Error('runtime unavailable'))
  const coverage = vi.spyOn(xcmaxEmployeeAutonomyApi, 'executionCoverage').mockRejectedValue(new Error('coverage unavailable'))
  await wrapper.get('.page-header button').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('runtime unavailable')
  expect(wrapper.findAll('.metric-card strong').map(item => item.text())).toEqual(['待核实', '待核实', '待核实', '待核实'])
  expect(wrapper.text()).not.toContain('没有失败或停摆任务')
  expect(wrapper.text()).not.toContain('全部员工均有有效能力回执')
  wrapper.unmount()
  runtime.mockRestore(); coverage.mockRestore()
})

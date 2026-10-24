import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import XCmaxAdminInfraTab from '../../../admin-console/src/components/admin/XCmaxAdminInfraTab.vue'
import { xcmaxOpsApi } from '@/api/xcmaxOps'
import { api } from '@/api'

vi.mock('@/api/xcmaxOps', () => ({ xcmaxOpsApi: { closureStatus: vi.fn(), dutyHealth: vi.fn() } }))
vi.mock('@/api', () => ({ api: { get: vi.fn() } }))
const complete = () => ({ deliverable: true, planned_employee_ids: ['e1', 'e2'], local_employee_pack_ids: ['e1', 'e2'], registered_employee_ids: ['e1', 'e2'], planned_local_installed_count: 2, missing_local_employee_packs: [], missing_remote_employees: [], blockers: [] })
const setup = () => mount(XCmaxAdminInfraTab, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(xcmaxOpsApi.closureStatus).mockResolvedValue(complete())
  vi.mocked(xcmaxOpsApi.dutyHealth).mockResolvedValue({ remote_health: { employee_scheduler: { running: true } } })
  vi.mocked(api.get).mockResolvedValue({ reachable: true })
})

it.each([true, false])('does not call partial installation ready even when the aggregate omits its blocker (%s)', async (reported) => {
  vi.mocked(xcmaxOpsApi.closureStatus).mockResolvedValue({ ...complete(), local_employee_pack_ids: ['e1'], planned_local_installed_count: 1, missing_local_employee_packs: reported ? ['e2'] : [], blockers: reported ? [{ code: 'LOCAL_EMPLOYEE_PACK_MISSING', count: 1, employee_ids: ['e2'] }] : [] })
  const wrapper = setup()
  await flushPromises()
  expect(wrapper.get('.status-badge').text()).toBe('尚有未闭环项')
  expect(wrapper.text()).toContain('当前运行端缺少员工包')
  expect(wrapper.text()).toContain('尚未记录，待指派')
  expect(wrapper.text()).toContain('核对市场权益与平台')
  expect(wrapper.text()).toContain('员工编号：e2')
  expect(wrapper.find('.badge-ok').exists()).toBe(false)
  wrapper.unmount()
})

it('keeps contradictory installation counts unverified', async () => {
  vi.mocked(xcmaxOpsApi.closureStatus).mockResolvedValue({ ...complete(), planned_local_installed_count: 1 })
  const wrapper = setup()
  await flushPromises()
  expect(wrapper.get('.status-badge').text()).toBe('安装计数待核对')
  expect(wrapper.find('.badge-ok').exists()).toBe(false)
  wrapper.unmount()
})

it('invalidates a previous ready state and keeps other successful sources when one read fails', async () => {
  const wrapper = setup()
  await flushPromises()
  expect(wrapper.get('.status-badge').text()).toBe('本次检查满足')
  vi.mocked(xcmaxOpsApi.closureStatus).mockRejectedValueOnce(new Error('网络中断'))
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.get('.status-badge').text()).toBe('部分状态待核实')
  expect(wrapper.get('[role="alert"]').text()).toContain('闭环依据读取失败')
  expect(wrapper.text()).toContain('可达')
  expect(wrapper.find('.badge-ok').exists()).toBe(false)
  wrapper.unmount()
})

it.each([{ ...complete(), blockers: [null] }, { deliverable: true }, { ...complete(), planned_employee_ids: [null] }])('keeps incomplete or malformed evidence unverified', async (reply) => {
  vi.mocked(xcmaxOpsApi.closureStatus).mockResolvedValue(reply)
  const wrapper = setup()
  await flushPromises()
  expect(wrapper.get('.status-badge').text()).toBe('部分状态待核实')
  expect(wrapper.find('.badge-ok').exists()).toBe(false)
  wrapper.unmount()
})

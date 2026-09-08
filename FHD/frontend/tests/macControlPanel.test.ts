import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MacControlPanel from '../../admin-console/src/components/admin/MacControlPanel.vue'

const api = vi.hoisted(() => ({ readFleet: vi.fn(), readTasks: vi.fn(), readTask: vi.fn(), submitControlTask: vi.fn(), cancelTask: vi.fn() }))
vi.mock('../src/api/macControl', () => api)

describe('Mac control panel', () => {
  beforeEach(() => {
    vi.clearAllMocks(); sessionStorage.clear()
    api.readFleet.mockResolvedValue({ enabled: true, freshness: 'stale', observed_at: 1, error: 'offline', devices: [{ id: 'mac', name: 'Mac', status: 'online', tools: [] }] })
    api.readTasks.mockResolvedValue({ tasks: [] })
  })
  it('shows expired observations as unverified instead of online', async () => {
    const wrapper = mount(MacControlPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('状态待核实')
    expect(wrapper.text()).toContain('数据缺失或过期')
    wrapper.unmount()
  })
  it('retains the idempotency key after response loss and remount', async () => {
    api.submitControlTask.mockRejectedValue(new Error('lost response'))
    let wrapper = mount(MacControlPanel)
    await flushPromises()
    await wrapper.get('textarea').setValue('检查设备')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    const key = api.submitControlTask.mock.calls[0][1]
    wrapper.unmount()
    wrapper = mount(MacControlPanel)
    await flushPromises()
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('检查设备')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(api.submitControlTask.mock.calls[1][1]).toBe(key)
    wrapper.unmount()
  })
})

it('keeps malformed customer evidence visible without claiming completion', async () => {
  sessionStorage.clear()
  api.readFleet.mockResolvedValue({ enabled: true, freshness: 'fresh', devices: [] })
  const task = { id: 'fixture', state: 'execution_completed', request: { message: 'fixture' }, execution: {}, delivery: { status: 'not_verified' } }
  api.readTasks.mockResolvedValue({ tasks: [task] })
  api.readTask.mockResolvedValue({ task: { ...task, facts: { observed_at: 1, tickets: [{ id: 1, error: 'invalid_delivery_evidence' }] } }, events: [] })
  const wrapper = mount(MacControlPanel)
  await flushPromises()
  const button = wrapper.findAll('button').find(button => button.text().includes('fixture'))
  expect(button).toBeTruthy()
  await button!.trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('证据读取失败，状态待核实')
  expect(wrapper.text()).not.toContain('业务系统已完成交付')
  wrapper.unmount()
})

it('separates release phases and distrusts a fresh cached fleet after a read error', async () => {
  sessionStorage.clear()
  api.readFleet.mockResolvedValue({ enabled: true, freshness: 'fresh', error: 'offline', devices: [{ id: 'mac', name: 'Mac', status: 'online', tools: [] }] })
  const task = { id: 'stages', state: 'execution_completed', request: { message: '阶段核验' }, execution: {}, delivery: { status: 'not_verified' }, delivery_trace: { freshness: 'fresh', observed_at: 1, stages: [{ name: 'tests', state: 'passed', source: 'github_check_runs' }, { name: 'merged', state: 'pending', source: 'github_pull_request' }, { name: 'business', state: 'unknown', source: 'customer_delivery_receipts' }] } }
  api.readTasks.mockResolvedValue({ tasks: [task] })
  api.readTask.mockResolvedValue({ task, events: [] })
  const wrapper = mount(MacControlPanel)
  await flushPromises()
  expect(wrapper.text()).toContain('状态待核实')
  await wrapper.findAll('button').find(button => button.text() === '阶段核验')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('CI 测试：检查通过')
  expect(wrapper.text()).toContain('主线合并：等待中')
  expect(wrapper.text()).toContain('客户业务验收：待核实')
  wrapper.unmount()
})

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

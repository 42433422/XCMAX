import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import MacControlPanel from '../../../admin-console/src/components/admin/MacControlPanel.vue'
import { readFleet, readTasks, submitControlTask } from '@/api/macControl'

vi.mock('@/api/macControl', () => ({ readFleet: vi.fn(), readTasks: vi.fn(), readTask: vi.fn(), cancelTask: vi.fn(), submitControlTask: vi.fn() }))
beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear() })

it.each([['fresh', 'online', false], ['fresh', 'offline', true], ['stale', 'online', true]] as const)(
  'distinguishes the last tool report from current execution: fleet=%s device=%s', async (freshness, status, unverified) => {
    vi.mocked(readFleet).mockResolvedValue({ enabled: true, freshness, error: '', observed_at: 1, primary_device_id: 'qa-device', devices: [
      { id: 'qa-device', name: '合成测试设备', status, last_seen: '2026-10-24', tools: [{ toolName: 'codex', status: 'running', currentTask: 'qa-task' }] },
    ] })
    vi.mocked(readTasks).mockResolvedValue({ tasks: [{ id: 'qa-task', state: 'reconciling', reason: 'dispatch_outcome_unknown_no_automatic_resubmit', request: { message: '合成修复任务', target: 'mac' }, para_task_id: '', updated_at: 1, execution: {}, delivery: { status: 'pending' } }] })
    const wrapper = mount(MacControlPanel)
    await flushPromises()
    const tool = wrapper.get('.devices article small:last-child').text()
    expect(tool).toContain('执行中 qa-task')
    expect(tool.includes('上次上报')).toBe(unverified)
    expect(tool.includes('当前执行情况待核实')).toBe(unverified)
    expect(wrapper.text()).toContain('派发结果尚未核实，系统不会自动重复派发')
    expect(wrapper.get('.tasks small').attributes('title')).toBe('dispatch_outcome_unknown_no_automatic_resubmit')
    expect(submitControlTask).not.toHaveBeenCalled()
    wrapper.unmount()
  },
)

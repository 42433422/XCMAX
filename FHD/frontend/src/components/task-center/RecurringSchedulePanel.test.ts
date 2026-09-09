import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import RecurringSchedulePanel from './RecurringSchedulePanel.vue'

const api = vi.hoisted(() => ({ listSchedules: vi.fn(), controlSchedule: vi.fn() }))
vi.mock('@/api/agentRuns', () => ({ default: api }))
const row = { schedule_id: 'schedule-1', state: 'active', next_run_at: '2030-01-01T00:00:00Z', last_error: '', payload: { title: '库存检查', recurrence: { kind: 'daily', hour: 0, timezone: 'Asia/Shanghai' } } }

describe('recurring schedule controls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listSchedules.mockResolvedValue({ success: true, data: [row] })
  })

  it('reads the authoritative state again after pausing', async () => {
    const wrapper = mount(RecurringSchedulePanel)
    await flushPromises()
    expect(wrapper.text()).toContain('每天 00:00')
    api.controlSchedule.mockResolvedValue({ success: true })
    api.listSchedules.mockResolvedValue({ success: true, data: [{ ...row, state: 'paused' }] })
    await wrapper.findAll('button').find(button => button.text() === '暂停')!.trigger('click')
    await flushPromises()
    expect(api.controlSchedule).toHaveBeenCalledWith('schedule-1', 'pause')
    expect(wrapper.text()).toContain('已暂停')
    expect(wrapper.text()).toContain('恢复')
    wrapper.unmount()
  })

  it('does not display an old account response after an account switch', async () => {
    let resolveOld!: (value: unknown) => void
    api.listSchedules.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
    const wrapper = mount(RecurringSchedulePanel)
    api.listSchedules.mockResolvedValue({ success: true, data: [] })
    productReadAccountEpoch.value++
    await flushPromises()
    resolveOld({ success: true, data: [row] })
    await flushPromises()
    expect(wrapper.text()).not.toContain('库存检查')
    expect(wrapper.text()).toContain('没有周期计划')
    wrapper.unmount()
  })

  it('keeps actual state when the server rejects cancellation', async () => {
    const wrapper = mount(RecurringSchedulePanel)
    await flushPromises()
    api.controlSchedule.mockResolvedValue({ success: false })
    await wrapper.findAll('button').find(button => button.text() === '取消计划')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('操作失败')
    expect(wrapper.text()).toContain('已启用')
    wrapper.unmount()
  })
})

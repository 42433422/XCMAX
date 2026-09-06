import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ValueStatsBar from './ValueStatsBar.vue'
import { estimateLaborCostSavedCny, formatCny } from '@/constants/valueStats'

const apiMock = vi.hoisted(() => ({
  getTaskRuntime: vi.fn(),
}))
vi.mock('@/api/agentRuns', () => ({ default: apiMock }))

function runtimeResponse(completedCount) {
  return {
    success: true,
    data: {
      running: true,
      max_workers: 4,
      active_count: 0,
      progress: {
        task_count: completedCount + 1,
        active_count: 0,
        attention_count: 0,
        completed_count: completedCount,
        overall_percent: 100,
      },
    },
  }
}

describe('ValueStatsBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('展示真实完成任务数与折算费用（1.9–5.8 元/单伪随机口径）', async () => {
    apiMock.getTaskRuntime.mockResolvedValue(runtimeResponse(8))
    const wrapper = mount(ValueStatsBar)
    await flushPromises()
    const text = wrapper.find('.value-stats-bar__text').text()
    expect(text).toContain('已为您解决')
    expect(text).toContain('8')
    expect(text).toContain(formatCny(estimateLaborCostSavedCny(8)))
    expect(text).not.toContain('—')
    wrapper.unmount()
  })

  it('0 单时如实显示 0', async () => {
    apiMock.getTaskRuntime.mockResolvedValue(runtimeResponse(0))
    const wrapper = mount(ValueStatsBar)
    await flushPromises()
    expect(wrapper.find('.value-stats-bar__text').text()).toContain('0')
    expect(wrapper.text()).toContain('¥0')
    wrapper.unmount()
  })

  it('接口失败静默降级为 —', async () => {
    apiMock.getTaskRuntime.mockRejectedValue(new Error('network down'))
    const wrapper = mount(ValueStatsBar)
    await flushPromises()
    expect(wrapper.text()).toContain('—')
    expect(wrapper.text()).not.toContain('¥')
    wrapper.unmount()
  })

  it('每 5 分钟自动刷新', async () => {
    vi.useFakeTimers()
    apiMock.getTaskRuntime.mockResolvedValue(runtimeResponse(3))
    const wrapper = mount(ValueStatsBar)
    await vi.advanceTimersByTimeAsync(0)
    expect(apiMock.getTaskRuntime).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000)
    expect(apiMock.getTaskRuntime).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000)
    expect(apiMock.getTaskRuntime).toHaveBeenCalledTimes(2)
  })
})

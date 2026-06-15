import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

// Mock fetch for health/metrics endpoints
const mockFetch = vi.fn().mockResolvedValue({
  ok: false,
  json: async () => ({}),
  text: async () => '',
})
vi.stubGlobal('fetch', mockFetch)

import MonitorModePanel from '@/components/pro-mode/MonitorModePanel.vue'

function mountComponent(propsOverrides = {}) {
  return mount(MonitorModePanel, {
    props: {
      isMonitorMode: true,
      ...propsOverrides,
    },
  })
}

describe('MonitorModePanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    mockFetch.mockReset()
    mockFetch.mockResolvedValue({
      ok: false,
      json: async () => ({}),
      text: async () => '',
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the panel container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.monitor-mode-panel').exists()).toBe(true)
  })

  it('renders the header with title', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.monitor-title').text()).toContain('系统监控面板')
  })

  it('renders close button', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.close-btn').exists()).toBe(true)
  })

  it('emits close event when close button clicked', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.close-btn').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('renders 4 metric cards', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.metric-card').length).toBe(4)
  })

  it('renders CPU metric card', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('CPU 使用率')
  })

  it('renders memory metric card', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('内存使用')
  })

  it('renders disk metric card', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('磁盘使用')
  })

  it('renders active requests metric card', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('活跃请求')
  })

  it('renders services section', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.services-section').exists()).toBe(true)
    expect(wrapper.text()).toContain('服务状态')
  })

  it('renders 4 default services', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.service-item').length).toBe(4)
  })

  it('renders alerts section', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.alerts-section').exists()).toBe(true)
  })

  it('shows no alerts message when empty', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('暂无告警')
  })

  it('renders logs section', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.logs-section').exists()).toBe(true)
  })

  it('renders action buttons', () => {
    const wrapper = mountComponent()
    const btns = wrapper.findAll('.action-btn')
    expect(btns.length).toBe(2)
    expect(btns[0].text()).toContain('刷新数据')
    expect(btns[1].text()).toContain('历史趋势')
  })

  it('emits viewHistory when history button clicked', async () => {
    const wrapper = mountComponent()
    const historyBtn = wrapper.findAll('.action-btn')[1]
    await historyBtn.trigger('click')
    expect(wrapper.emitted('viewHistory')).toBeTruthy()
  })

  it('calls fetch on mount', () => {
    mountComponent()
    expect(mockFetch).toHaveBeenCalled()
  })

  it('sets up refresh interval on mount', () => {
    mountComponent()
    vi.advanceTimersByTime(10000)
    // fetch called multiple times due to interval
    expect(mockFetch.mock.calls.length).toBeGreaterThan(1)
  })

  it('applies monitor-mode class when isMonitorMode is true', () => {
    const wrapper = mountComponent({ isMonitorMode: true })
    expect(wrapper.find('.monitor-mode-panel.monitor-mode').exists()).toBe(true)
  })

  it('clears interval on unmount', () => {
    const wrapper = mountComponent()
    const clearIntervalSpy = vi.spyOn(global, 'clearInterval')
    wrapper.unmount()
    expect(clearIntervalSpy).toHaveBeenCalled()
  })

  it('refresh button triggers data fetch', async () => {
    mockFetch.mockClear()
    const wrapper = mountComponent()
    mockFetch.mockClear()
    const refreshBtn = wrapper.findAll('.action-btn')[0]
    await refreshBtn.trigger('click')
    expect(mockFetch).toHaveBeenCalled()
  })

  it('CPU metric card click triggers refresh', async () => {
    mockFetch.mockClear()
    const wrapper = mountComponent()
    mockFetch.mockClear()
    const cpuCard = wrapper.find('.metric-card.cpu')
    await cpuCard.trigger('click')
    expect(mockFetch).toHaveBeenCalled()
  })

  it('renders metric bar fills', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.metric-bar-fill').length).toBe(3)
  })

  it('renders service status dots', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.service-status-dot').length).toBe(4)
  })

  it('renders refresh hint text', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('点击指标卡刷新')
  })
})

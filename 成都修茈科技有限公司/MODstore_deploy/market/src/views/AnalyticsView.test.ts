import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import AnalyticsView from './AnalyticsView.vue'

vi.mock('../api', () => ({
  api: {
    analyticsDashboard: vi.fn(),
  },
}))

import { api } from '../api'

describe('AnalyticsView', () => {
  let router: ReturnType<typeof createRouter>

  beforeEach(() => {
    vi.clearAllMocks()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', name: 'analytics', component: { template: '<div />' } }],
    })
  })

  it('renders title and description', async () => {
    vi.mocked(api.analyticsDashboard).mockResolvedValue({
      execution: { total: 0, success: 0, failed: 0, success_rate: 0, total_tokens: 0 },
      spending: { total: 0 },
      recent_executions: [],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(AnalyticsView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('使用统计')
    expect(wrapper.text()).toContain('员工执行次数')
  })

  it('shows loading state initially', async () => {
    vi.mocked(api.analyticsDashboard).mockReturnValue(new Promise(() => {}))
    router.push('/')
    await router.isReady()

    const wrapper = mount(AnalyticsView, { global: { plugins: [router] } })
    expect(wrapper.text()).toContain('加载中')
  })

  it('renders execution stats', async () => {
    vi.mocked(api.analyticsDashboard).mockResolvedValue({
      execution: { total: 42, success: 38, failed: 4, success_rate: 90.5, total_tokens: 12345 },
      spending: { total: 99.9 },
      recent_executions: [],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(AnalyticsView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('42')
    expect(wrapper.text()).toContain('90.5%')
    expect(wrapper.text()).toContain('12345')
  })

  it('renders spending stats', async () => {
    vi.mocked(api.analyticsDashboard).mockResolvedValue({
      execution: { total: 0, success: 0, failed: 0, success_rate: 0, total_tokens: 0 },
      spending: { total: 256.8 },
      recent_executions: [],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(AnalyticsView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('256.80')
  })

  it('renders recent executions table', async () => {
    vi.mocked(api.analyticsDashboard).mockResolvedValue({
      execution: { total: 1, success: 1, failed: 0, success_rate: 100, total_tokens: 100 },
      spending: { total: 0 },
      recent_executions: [
        { id: 1, employee_id: 'emp-1', task: 'test task', status: 'done', llm_tokens: 50, created_at: '2026-01-01' },
      ],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(AnalyticsView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('emp-1')
    expect(wrapper.text()).toContain('test task')
  })

  it('shows empty state for no recent executions', async () => {
    vi.mocked(api.analyticsDashboard).mockResolvedValue({
      execution: { total: 0, success: 0, failed: 0, success_rate: 0, total_tokens: 0 },
      spending: { total: 0 },
      recent_executions: [],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(AnalyticsView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('暂无执行记录')
  })

  it('shows error message on API failure', async () => {
    vi.mocked(api.analyticsDashboard).mockRejectedValue(new Error('Network error'))
    router.push('/')
    await router.isReady()

    const wrapper = mount(AnalyticsView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Network error')
  })

  it('handles missing execution data gracefully', async () => {
    vi.mocked(api.analyticsDashboard).mockResolvedValue({})
    router.push('/')
    await router.isReady()

    const wrapper = mount(AnalyticsView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('0')
  })
})

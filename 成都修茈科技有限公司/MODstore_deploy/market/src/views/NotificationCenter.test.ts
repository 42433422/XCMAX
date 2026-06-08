import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { setActivePinia, createPinia } from 'pinia'
import NotificationCenter from './NotificationCenter.vue'
import { api } from '../api'
import { useNotificationStore } from '../stores/notifications'

vi.mock('../api', () => ({
  api: {
    notificationsList: vi.fn(),
  },
}))

describe('NotificationCenter', () => {
  let router: ReturnType<typeof createRouter>

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'notifications', component: { template: '<div />' } },
        { path: '/wallet', name: 'wallet', component: { template: '<div />' } },
        { path: '/orders/:orderId', name: 'order-detail', component: { template: '<div />' } },
        { path: '/workbench', name: 'workbench', component: { template: '<div />' } },
      ],
    })
  })

  it('renders title and empty state', async () => {
    vi.mocked(api.notificationsList).mockResolvedValue({ notifications: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(NotificationCenter, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('通知中心')
    expect(wrapper.text()).toContain('暂无通知')
  })

  it('renders notification items', async () => {
    vi.mocked(api.notificationsList).mockResolvedValue({
      notifications: [
        { id: 1, title: '支付成功', content: '订单已支付', is_read: true, created_at: '2024-01-01', type: 'payment_success', data: {} },
        { id: 2, title: '配额警告', content: '余额不足', is_read: false, created_at: '2024-01-02', type: 'quota_warning', data: {} },
      ],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(NotificationCenter, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('支付成功')
    expect(wrapper.text()).toContain('配额警告')
    expect(wrapper.text()).toContain('标为已读')
  })

  it('renders filter chips', async () => {
    vi.mocked(api.notificationsList).mockResolvedValue({ notifications: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(NotificationCenter, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('全部')
    expect(wrapper.text()).toContain('支付')
    expect(wrapper.text()).toContain('员工')
    expect(wrapper.text()).toContain('配额')
    expect(wrapper.text()).toContain('系统')
  })

  it('shows error message on API failure', async () => {
    vi.mocked(api.notificationsList).mockRejectedValue(new Error('Network error'))
    router.push('/')
    await router.isReady()

    const wrapper = mount(NotificationCenter, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Network error')
  })

  it('shows loading state initially', async () => {
    vi.mocked(api.notificationsList).mockReturnValue(new Promise(() => {}))
    router.push('/')
    await router.isReady()

    const wrapper = mount(NotificationCenter, {
      global: { plugins: [router] },
    })

    expect(wrapper.text()).toContain('加载中')
  })
})

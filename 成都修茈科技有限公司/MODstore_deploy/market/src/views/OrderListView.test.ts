import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import OrderListView from './OrderListView.vue'

vi.mock('../api', () => ({
  api: {
    paymentOrders: vi.fn(),
    paymentDismissNonActiveOrders: vi.fn(),
    paymentCancelOrder: vi.fn(),
  },
}))

import { api } from '../api'

describe('OrderListView', () => {
  let router: ReturnType<typeof createRouter>

  beforeEach(() => {
    vi.clearAllMocks()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'orders', component: { template: '<div />' } },
        { path: '/orders/:orderId', name: 'order-detail', component: { template: '<div />' } },
        { path: '/refunds', name: 'refunds', component: { template: '<div />' } },
      ],
    })
  })

  it('renders title', async () => {
    vi.mocked(api.paymentOrders).mockResolvedValue({ orders: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('我的订单')
  })

  it('shows loading state', async () => {
    vi.mocked(api.paymentOrders).mockReturnValue(new Promise(() => {}))
    router.push('/')
    await router.isReady()

    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    expect(wrapper.text()).toContain('加载中')
  })

  it('shows empty state', async () => {
    vi.mocked(api.paymentOrders).mockResolvedValue({ orders: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('暂无订单')
  })

  it('renders order list', async () => {
    vi.mocked(api.paymentOrders).mockResolvedValue({
      orders: [
        { out_trade_no: 'ORD-001', status: 'paid', subject: '套餐购买', total_amount: '99.9', created_at: '2026-01-01' },
        { out_trade_no: 'ORD-002', status: 'pending', subject: '商品购买', total_amount: '50', created_at: '2026-01-02' },
      ],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('ORD-001')
    expect(wrapper.text()).toContain('ORD-002')
    expect(wrapper.text()).toContain('已支付')
    expect(wrapper.text()).toContain('待支付')
  })

  it('renders filter buttons', async () => {
    vi.mocked(api.paymentOrders).mockResolvedValue({ orders: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('全部')
    expect(wrapper.text()).toContain('待支付')
    expect(wrapper.text()).toContain('已支付')
    expect(wrapper.text()).toContain('已关闭')
  })

  it('shows refund button for paid orders', async () => {
    vi.mocked(api.paymentOrders).mockResolvedValue({
      orders: [
        { out_trade_no: 'ORD-001', status: 'paid', subject: '套餐', total_amount: '99', created_at: '2026-01-01' },
      ],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('申请退款')
  })

  it('shows cancel button for pending orders', async () => {
    vi.mocked(api.paymentOrders).mockResolvedValue({
      orders: [
        { out_trade_no: 'ORD-001', status: 'pending', subject: '套餐', total_amount: '99', created_at: '2026-01-01' },
      ],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('取消')
  })

  it('shows error on API failure', async () => {
    vi.mocked(api.paymentOrders).mockRejectedValue(new Error('Network error'))
    router.push('/')
    await router.isReady()

    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Network error')
  })

  it('shows dismiss button when orders exist', async () => {
    vi.mocked(api.paymentOrders).mockResolvedValue({
      orders: [
        { out_trade_no: 'ORD-001', status: 'paid', subject: '套餐', total_amount: '99', created_at: '2026-01-01' },
      ],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('清理展示')
  })

  it('reloads orders on filter click', async () => {
    vi.mocked(api.paymentOrders).mockResolvedValue({ orders: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    await flushPromises()

    const filterBtns = wrapper.findAll('.filter-btn')
    await filterBtns[1].trigger('click')
    await flushPromises()

    expect(api.paymentOrders).toHaveBeenCalledTimes(2)
  })
})

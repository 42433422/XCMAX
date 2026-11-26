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
    vi.resetAllMocks()
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
        {
          out_trade_no: 'ORD-001',
          status: 'paid',
          subject: '套餐购买',
          total_amount: '99.9',
          created_at: '2026-01-01',
        },
        {
          out_trade_no: 'ORD-002',
          status: 'pending',
          subject: '商品购买',
          total_amount: '50',
          created_at: '2026-01-02',
        },
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
        {
          out_trade_no: 'ORD-001',
          status: 'paid',
          subject: '套餐',
          total_amount: '99',
          created_at: '2026-01-01',
        },
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
        {
          out_trade_no: 'ORD-001',
          status: 'pending',
          subject: '套餐',
          total_amount: '99',
          created_at: '2026-01-01',
        },
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
        {
          out_trade_no: 'ORD-001',
          status: 'paid',
          subject: '套餐',
          total_amount: '99',
          created_at: '2026-01-01',
        },
      ],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('清理展示')
  })

  it('discards an older filter response and keeps the most recently requested order list', async () => {
    let finishOlder!: (result: { orders: { out_trade_no: string }[] }) => void
    vi.mocked(api.paymentOrders)
      .mockImplementationOnce(() => new Promise((resolve) => { finishOlder = resolve }))
      .mockResolvedValueOnce({ orders: [{ out_trade_no: 'NEW-PAID', status: 'paid' }] })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    await wrapper.findAll('.filter-btn')[2].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('NEW-PAID')
    finishOlder({ orders: [{ out_trade_no: 'OLD-PENDING' }] })
    await flushPromises()
    expect(wrapper.text()).toContain('NEW-PAID')
    expect(wrapper.text()).not.toContain('OLD-PENDING')
    expect(wrapper.get('.order-card').attributes('tabindex')).toBe('0')
    wrapper.unmount()
  })

  it('exposes retry after a failed order read and does not label errors as empty data', async () => {
    vi.mocked(api.paymentOrders)
      .mockRejectedValueOnce(new Error('请求超时'))
      .mockResolvedValueOnce({ orders: [{ out_trade_no: 'RETRY-OK' }] })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(OrderListView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('请求超时')
    expect(wrapper.text()).not.toContain('暂无订单')
    await wrapper.get('.retry-btn').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('RETRY-OK')
    wrapper.unmount()
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

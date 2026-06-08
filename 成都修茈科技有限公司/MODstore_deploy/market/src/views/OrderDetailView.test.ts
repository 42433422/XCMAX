import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import OrderDetailView from './OrderDetailView.vue'

vi.mock('../api', () => ({
  api: {
    paymentQuery: vi.fn(),
  },
}))

import { api } from '../api'

describe('OrderDetailView', () => {
  let router: ReturnType<typeof createRouter>

  beforeEach(() => {
    vi.clearAllMocks()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/orders/:orderId', name: 'order-detail', component: OrderDetailView },
        { path: '/plans', name: 'plans', component: { template: '<div />' } },
        { path: '/refunds', name: 'refunds', component: { template: '<div />' } },
        { path: '/wallet/purchased', name: 'wallet-purchased', component: { template: '<div />' } },
      ],
    })
  })

  it('renders loading state initially', async () => {
    vi.mocked(api.paymentQuery).mockReturnValue(new Promise(() => {}))
    router.push('/orders/ORD-001')
    await router.isReady()

    const wrapper = mount(OrderDetailView, { global: { plugins: [router] } })
    expect(wrapper.text()).toContain('加载中')
  })

  it('renders order detail', async () => {
    vi.mocked(api.paymentQuery).mockResolvedValue({
      out_trade_no: 'ORD-001',
      subject: 'VIP 套餐',
      total_amount: '99.9',
      status: 'paid',
      trade_no: 'ALI-123',
      created_at: '2026-01-01T10:00:00Z',
      paid_at: '2026-01-01T10:01:00Z',
      refund_status: 'none',
      refunded_amount: 0,
    })
    router.push('/orders/ORD-001')
    await router.isReady()

    const wrapper = mount(OrderDetailView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('ORD-001')
    expect(wrapper.text()).toContain('VIP 套餐')
    expect(wrapper.text()).toContain('99.9')
    expect(wrapper.text()).toContain('已支付')
    expect(wrapper.text()).toContain('ALI-123')
  })

  it('shows not found when order does not exist', async () => {
    vi.mocked(api.paymentQuery).mockRejectedValue(new Error('Not found'))
    router.push('/orders/INVALID')
    await router.isReady()

    const wrapper = mount(OrderDetailView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('订单不存在')
  })

  it('shows refund button for paid orders', async () => {
    vi.mocked(api.paymentQuery).mockResolvedValue({
      out_trade_no: 'ORD-001',
      subject: '套餐',
      total_amount: '99',
      status: 'paid',
      trade_no: '',
      created_at: '2026-01-01',
      refund_status: 'none',
      refunded_amount: 0,
    })
    router.push('/orders/ORD-001')
    await router.isReady()

    const wrapper = mount(OrderDetailView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('申请退款')
  })

  it('does not show refund button for non-paid orders', async () => {
    vi.mocked(api.paymentQuery).mockResolvedValue({
      out_trade_no: 'ORD-001',
      subject: '套餐',
      total_amount: '99',
      status: 'pending',
      trade_no: '',
      created_at: '2026-01-01',
      refund_status: 'none',
      refunded_amount: 0,
    })
    router.push('/orders/ORD-001')
    await router.isReady()

    const wrapper = mount(OrderDetailView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).not.toContain('申请退款')
  })

  it('displays refund status', async () => {
    vi.mocked(api.paymentQuery).mockResolvedValue({
      out_trade_no: 'ORD-001',
      subject: '套餐',
      total_amount: '99',
      status: 'paid',
      trade_no: '',
      created_at: '2026-01-01',
      paid_at: '2026-01-01',
      refund_status: 'pending',
      refunded_amount: 0,
    })
    router.push('/orders/ORD-001')
    await router.isReady()

    const wrapper = mount(OrderDetailView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('审核中')
  })

  it('shows dash for missing trade number', async () => {
    vi.mocked(api.paymentQuery).mockResolvedValue({
      out_trade_no: 'ORD-001',
      subject: '套餐',
      total_amount: '99',
      status: 'paid',
      created_at: '2026-01-01',
      refund_status: 'none',
      refunded_amount: 0,
    })
    router.push('/orders/ORD-001')
    await router.isReady()

    const wrapper = mount(OrderDetailView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('—')
  })
})

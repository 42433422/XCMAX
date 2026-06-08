import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import WalletRechargeView from './WalletRechargeView.vue'

vi.mock('../api', () => ({
  api: {
    balance: vi.fn(),
    paymentCheckout: vi.fn(),
    paymentQuery: vi.fn(),
  },
}))

import { api } from '../api'

describe('WalletRechargeView', () => {
  let router: ReturnType<typeof createRouter>

  beforeEach(() => {
    vi.clearAllMocks()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'recharge', component: { template: '<div />' } },
        { path: '/wallet', name: 'wallet', component: { template: '<div />' } },
        { path: '/checkout/:orderId', name: 'checkout', component: { template: '<div />' } },
      ],
    })
  })

  it('renders title and preset amounts', async () => {
    vi.mocked(api.balance).mockResolvedValue({ balance: 100 })
    router.push('/')
    await router.isReady()

    const wrapper = mount(WalletRechargeView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('钱包充值')
    expect(wrapper.text()).toContain('¥10')
    expect(wrapper.text()).toContain('¥50')
    expect(wrapper.text()).toContain('¥100')
    expect(wrapper.text()).toContain('¥200')
    expect(wrapper.text()).toContain('¥500')
    expect(wrapper.text()).toContain('¥1000')
  })

  it('displays current balance', async () => {
    vi.mocked(api.balance).mockResolvedValue({ balance: 256.8 })
    router.push('/')
    await router.isReady()

    const wrapper = mount(WalletRechargeView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('256.80')
  })

  it('shows pay button', async () => {
    vi.mocked(api.balance).mockResolvedValue({ balance: 0 })
    router.push('/')
    await router.isReady()

    const wrapper = mount(WalletRechargeView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('立即支付')
  })

  it('enables pay button when amount is selected', async () => {
    vi.mocked(api.balance).mockResolvedValue({ balance: 0 })
    router.push('/')
    await router.isReady()

    const wrapper = mount(WalletRechargeView, { global: { plugins: [router] } })
    await flushPromises()

    const btn = wrapper.find('.btn-primary')
    expect(btn.attributes('disabled')).toBeUndefined()
  })

  it('shows error on checkout failure', async () => {
    vi.mocked(api.balance).mockResolvedValue({ balance: 100 })
    vi.mocked(api.paymentCheckout).mockRejectedValue(new Error('支付失败'))
    router.push('/')
    await router.isReady()

    const wrapper = mount(WalletRechargeView, { global: { plugins: [router] } })
    await flushPromises()

    const amountBtns = wrapper.findAll('.amount-btn')
    await amountBtns[0].trigger('click')

    const payBtn = wrapper.find('.btn-primary')
    await payBtn.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('支付失败')
  })

  it('handles balance fetch failure gracefully', async () => {
    vi.mocked(api.balance).mockRejectedValue(new Error('fail'))
    router.push('/')
    await router.isReady()

    const wrapper = mount(WalletRechargeView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('钱包充值')
  })
})

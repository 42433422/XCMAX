import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import PaymentPlansView from './public/PaymentPlansView.vue'
import { ACCESS_TOKEN_KEY } from '../infrastructure/storage/tokenStore'

vi.mock('../api', () => ({
  api: {
    paymentPlans: vi.fn(),
    paymentMyPlan: vi.fn(),
    paymentCheckout: vi.fn(),
  },
}))

import { api } from '../api'

describe('PaymentPlansView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.paymentPlans).mockResolvedValue({
      plans: [
        {
          id: 'plan_basic',
          name: '基础版',
          price: 9.9,
          description: '适合试用',
          features: ['1 个员工'],
          requires_plan: false,
        },
      ],
    })
    vi.mocked(api.paymentMyPlan).mockResolvedValue({ plan: null, membership: null })
  })

  it('renders plan cards after load', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/plans', name: 'plans', component: PaymentPlansView }],
    })
    const pinia = createPinia()
    const wrapper = mount(PaymentPlansView, {
      global: { plugins: [pinia, router] },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('基础版')
    expect(wrapper.text()).toContain('¥9.90')
  })

  it('navigates to checkout on precreate response', async () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, 't1')
    vi.mocked(api.paymentCheckout).mockResolvedValue({
      ok: true,
      type: 'precreate',
      order_id: 'ord-99',
    })

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/plans', name: 'plans', component: PaymentPlansView }],
    })
    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as any)
    const pinia = createPinia()
    const wrapper = mount(PaymentPlansView, {
      global: { plugins: [pinia, router] },
    })

    await flushPromises()
    await wrapper.get('.plan-card .btn-primary').trigger('click')
    await flushPromises()

    expect(pushSpy).toHaveBeenCalledWith({ name: 'checkout', params: { orderId: 'ord-99' } })
  })
})

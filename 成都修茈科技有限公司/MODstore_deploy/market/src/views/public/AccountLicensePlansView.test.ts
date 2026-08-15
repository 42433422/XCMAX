import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AccountLicensePlansView from './AccountLicensePlansView.vue'

const apiMock = vi.hoisted(() => ({
  paymentAccountPlans: vi.fn(),
  paymentCheckout: vi.fn(),
}))
const hasTokenMock = vi.hoisted(() => vi.fn(() => true))

vi.mock('@/api', () => ({ api: apiMock }))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasToken: hasTokenMock }),
}))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/account-plans', name: 'account-plans', component: AccountLicensePlansView },
      { path: '/login', name: 'login', component: { template: '<div />' } },
      { path: '/checkout/:orderId', name: 'checkout', component: { template: '<div />' } },
    ],
  })
}

describe('AccountLicensePlansView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    hasTokenMock.mockReturnValue(true)
    apiMock.paymentAccountPlans.mockResolvedValue({
      plans: [
        {
          id: 'saas-trial-30',
          name: '30 天试用',
          description: '99 元试用',
          price: 99,
          amount_cents: 9900,
          catalog: 'account_license',
          license_type: 'trial',
          account_tier: 'normal',
          badge: '试用',
          features: ['XCAGI 桌面端账号授权'],
        },
      ],
    })
  })

  it('explains that account licenses differ from VIP/SVIP and creates the selected order', async () => {
    const router = makeRouter()
    await router.push('/account-plans?plan=saas-trial-30')
    await router.isReady()
    apiMock.paymentCheckout.mockResolvedValue({
      ok: true,
      type: 'precreate',
      order_id: 'ORDER-1',
    })

    const wrapper = mount(AccountLicensePlansView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('VIP / SVIP 是 AI 额度会员')
    expect(wrapper.text()).toContain('30 天试用')
    expect(wrapper.find('.license-card--requested').exists()).toBe(true)

    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(apiMock.paymentCheckout).toHaveBeenCalledWith({ plan_id: 'saas-trial-30' })
    expect(router.currentRoute.value.name).toBe('checkout')
    expect(router.currentRoute.value.params.orderId).toBe('ORDER-1')
  })

  it('sends an anonymous visitor to the separate login page', async () => {
    hasTokenMock.mockReturnValue(false)
    const router = makeRouter()
    await router.push('/account-plans')
    await router.isReady()
    const wrapper = mount(AccountLicensePlansView, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('login')
    expect(apiMock.paymentCheckout).not.toHaveBeenCalled()
  })
})

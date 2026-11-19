import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AccountLicensePlansView from './AccountLicensePlansView.vue'

const apiMock = vi.hoisted(() => ({
  activatePersonalPlan: vi.fn(),
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
          name: '30 天全功能体验',
          description: '用 30 天完整体验 XCAGI，包含 100 元 AI 使用额度。',
          price: 99,
          amount_cents: 9900,
          catalog: 'account_license',
          license_type: 'trial',
          account_tier: 'normal',
          badge: '体验',
          features: ['XCAGI 桌面端完整功能'],
        },
      ],
    })
  })

  it('activates the free personal plan without checkout', async () => {
    const router = makeRouter()
    await router.push('/account-plans')
    await router.isReady()
    apiMock.paymentAccountPlans.mockResolvedValueOnce({
      plans: [{ id: 'saas-personal-free', name: '个人使用版', price: 0, license_type: 'free' }],
    })
    apiMock.activatePersonalPlan.mockResolvedValueOnce({ ok: true })
    const wrapper = mount(AccountLicensePlansView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.get('button').text()).toBe('免费开通')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(apiMock.activatePersonalPlan).toHaveBeenCalledOnce()
    expect(apiMock.paymentCheckout).not.toHaveBeenCalled()
    expect(wrapper.get('[role="status"]').text()).toContain('个人使用版已开通')
  })

  it('presents customer-friendly plans and creates the selected order', async () => {
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

    expect(wrapper.text()).toContain('选择适合你的方案')
    expect(wrapper.text()).toContain('完成支付后即可在 XCAGI 登录使用')
    expect(wrapper.text()).toContain('30 天全功能体验')
    expect(wrapper.text()).not.toContain('账号授权')
    expect(wrapper.text()).not.toContain('VIP / SVIP')
    expect(wrapper.find('.license-card--requested').exists()).toBe(true)

    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(apiMock.paymentCheckout).toHaveBeenCalledWith({ plan_id: 'saas-trial-30' })
    expect(router.currentRoute.value.name).toBe('checkout')
    expect(router.currentRoute.value.params.orderId).toBe('ORDER-1')
  })

  it('does not expose underlying checkout failures', async () => {
    const router = makeRouter()
    await router.push('/account-plans')
    await router.isReady()
    apiMock.paymentCheckout.mockRejectedValue(new Error('database DSN leaked'))

    const wrapper = mount(AccountLicensePlansView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('暂时无法前往支付，请稍后重试。')
    expect(wrapper.text()).not.toContain('database DSN leaked')
  })

  it('preserves the mobile source while asking a visitor to log in', async () => {
    hasTokenMock.mockReturnValue(false)
    const router = makeRouter()
    await router.push('/account-plans?source=xcagi-mobile')
    await router.isReady()
    const wrapper = mount(AccountLicensePlansView, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query).toEqual({
      redirect: '/account-plans?source=xcagi-mobile',
      source: 'xcagi-mobile',
    })
    expect(apiMock.paymentCheckout).not.toHaveBeenCalled()
  })
})

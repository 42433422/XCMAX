import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import SaasPricingView from './SaasPricingView.vue'

const mocks = vi.hoisted(() => ({ getPlans: vi.fn(), checkout: vi.fn(), subscription: vi.fn(), handoff: vi.fn() }))
vi.mock('@/api/modelPayment', () => ({ default: { getPlans: mocks.getPlans, checkout: mocks.checkout } }))
vi.mock('@/api/auth', () => ({ authApi: { getSubscriptionStatus: mocks.subscription } }))
vi.mock('@/api/marketAccount', () => ({ createMarketBrowserHandoff: mocks.handoff }))
vi.mock('@/constants/loginBranding', () => ({ marketBaseUrl: () => 'https://xiu-ci.com/market' }))
const standard = { id: 'saas-permanent-standard', title: 'XCAGI 软件', amount_cents: 300000, description: '企业标准功能永久使用' }
const trial = { id: 'saas-trial-30', title: '30 天企业功能体验', amount_cents: 9900, duration_days: 30, description: '包含活动 AI 额度' }

async function open(query: Record<string, string> = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/saas-pricing', component: SaasPricingView },
    { path: '/enterprise-customer-service', component: { template: '<div />' } },
    { path: '/settings', component: { template: '<div />' } },
  ] })
  await router.push({ path: '/saas-pricing', query })
  const wrapper = mount(SaasPricingView, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.resetAllMocks()
  mocks.getPlans.mockResolvedValue({ success: true, data: {
    plans: [trial, standard, { id: 'saas-permanent-growth', title: '旧成长版', amount_cents: 9999900 }],
    commercial_terms: { customization_from_cents: 99900 },
  } })
  mocks.subscription.mockResolvedValue(null)
  Object.defineProperty(window, 'xcagiDesktop', { value: {}, configurable: true })
  vi.spyOn(window, 'open').mockReturnValue(null)
  mocks.handoff.mockImplementation(async (target: string, purpose: string) => ({ code: 'a'.repeat(43), target, purpose, expires_in: 60 }))
})

afterEach(() => {
  Reflect.deleteProperty(window, 'xcagiDesktop')
  vi.restoreAllMocks()
})

describe('SaasPricingView simple commerce', () => {
  it('offers one permanent product and separates customization and AI charges', async () => {
    const { wrapper } = await open({ budget: 'high' })
    expect(mocks.getPlans).toHaveBeenCalledWith()
    expect(wrapper.get('h1').text()).toBe('软件一次买断，按需定制')
    expect(wrapper.get('.saas-plan-card--recommended').text()).toContain('¥3,000')
    expect(wrapper.text()).toContain('¥999 起')
    expect(wrapper.text()).toContain('AI 调用按实际用量付费')
    expect(wrapper.text()).not.toMatch(/旧成长版|按预算推荐|选择套餐/)
    expect(wrapper.get('a[href="/enterprise-customer-service"]').text()).toBe('咨询定制')
    expect(wrapper.get('a[href="/settings?section=model-payment"]').text()).toContain('AI 费用')
    expect(wrapper.text()).toContain('个人基础功能，不含企业业务模块')
    expect(wrapper.get('.saas-test-entry').attributes('open')).toBeUndefined()
    expect(wrapper.get('.saas-test-entry').text()).toContain('¥99 / 30 天')
  })

  it('hands the selected software to market before checkout so the market creates the only order', async () => {
    const { wrapper } = await open()
    await wrapper.get('.saas-plan-card--recommended button').trigger('click')
    await flushPromises()
    expect(mocks.handoff).toHaveBeenCalledExactlyOnceWith('/plans?plan=saas-permanent-standard&source=fhd', 'plans')
    expect(window.open).toHaveBeenCalledExactlyOnceWith('https://xiu-ci.com/plans?plan=saas-permanent-standard&source=fhd#xcagi_code=' + 'a'.repeat(43), '_blank', 'noopener,noreferrer')
    expect(mocks.checkout).not.toHaveBeenCalled()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('keeps the existing trial as a secondary checkout', async () => {
    const { wrapper } = await open({ plan: 'saas-trial-30' })
    expect(wrapper.get('.saas-test-entry').attributes('open')).toBeDefined()
    await wrapper.get('.saas-test-entry button').trigger('click')
    await flushPromises()
    expect(mocks.handoff).toHaveBeenCalledExactlyOnceWith('/plans?plan=saas-trial-30&source=fhd', 'plans')
    expect(mocks.checkout).not.toHaveBeenCalled()
  })

  it('does not fabricate purchasable plans or a customization price on loading failure', async () => {
    mocks.getPlans.mockRejectedValue(new Error('private gateway'))
    const { wrapper } = await open()
    expect(wrapper.get('[role="alert"]').text()).toContain('暂时无法加载价格')
    expect(wrapper.find('.saas-plan-card--recommended').exists()).toBe(false)
    expect(wrapper.text()).not.toMatch(/private gateway|999|3,000/)
    expect(mocks.checkout).not.toHaveBeenCalled()
  })

  it('reports a payment failure without claiming activation or leaking the error', async () => {
    mocks.handoff.mockRejectedValue(new Error('private gateway'))
    const { wrapper } = await open()
    await wrapper.get('.saas-plan-card--recommended button').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('暂时无法前往支付')
    expect(wrapper.text()).not.toMatch(/private gateway|已开通|已到账/)
    expect(mocks.checkout).not.toHaveBeenCalled()
  })

  it('disables repeat purchases for an existing legacy permanent license', async () => {
    mocks.subscription.mockResolvedValue({ data: { active: true, plan_id: 'saas-permanent-growth' } })
    const { wrapper } = await open()
    expect(wrapper.get('h1').text()).toBe('XCAGI 软件已开通')
    expect(wrapper.get('.saas-plan-card--recommended button').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.saas-test-entry button').attributes('disabled')).toBeDefined()
    await wrapper.get('.saas-plan-card--recommended button').trigger('click')
    expect(mocks.handoff).not.toHaveBeenCalled()
    expect(mocks.checkout).not.toHaveBeenCalled()
  })

  it('shows the actual trial state and rejects an external return path', async () => {
    mocks.subscription.mockResolvedValue({ data: { reason: 'trial', trial_days_remaining: 7 } })
    const { wrapper, router } = await open({ redirect: '//external.example' })
    expect(wrapper.get('.saas-trial-hint').text()).toContain('7 天')
    await wrapper.get('.saas-back-link').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/')
  })
})

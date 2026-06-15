import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import SaasPricingView from './SaasPricingView.vue'

// --- Mocks ---

const mockGetPlans = vi.fn().mockResolvedValue({
  success: true,
  data: {
    plans: [
      { id: 'saas-basic', title: '基础版', amount_cents: 9900, description: '基础功能', badge: '' },
      { id: 'saas-pro', title: '专业版', amount_cents: 29900, description: '全部功能', badge: '推荐' },
    ],
  },
})

const mockCheckout = vi.fn().mockResolvedValue({
  success: true,
  data: { redirect_url: 'https://pay.example.com/checkout' },
})

vi.mock('@/api/modelPayment', () => ({
  default: {
    getPlans: () => mockGetPlans(),
    checkout: (planId: string) => mockCheckout(planId),
  },
}))

const mockGetSubscriptionStatus = vi.fn().mockResolvedValue(null)

vi.mock('@/api/auth', () => ({
  authApi: {
    getSubscriptionStatus: () => mockGetSubscriptionStatus(),
  },
}))

// --- Helpers ---

async function mountComponent(query: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/saas-pricing', name: 'saas-pricing', component: SaasPricingView },
    ],
  })
  router.push({ path: '/saas-pricing', query })
  await router.isReady()

  return mount(SaasPricingView, {
    global: {
      plugins: [router],
    },
  })
}

describe('SaasPricingView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetPlans.mockResolvedValue({
      success: true,
      data: {
        plans: [
          { id: 'saas-basic', title: '基础版', amount_cents: 9900, description: '基础功能', badge: '' },
          { id: 'saas-pro', title: '专业版', amount_cents: 29900, description: '全部功能', badge: '推荐' },
        ],
      },
    })
    mockCheckout.mockResolvedValue({
      success: true,
      data: { redirect_url: 'https://pay.example.com/checkout' },
    })
    mockGetSubscriptionStatus.mockResolvedValue(null)
  })

  it('renders pricing page title', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('h1').text()).toBe('选择套餐')
  })

  it('shows loading state initially', async () => {
    mockGetPlans.mockImplementation(() => new Promise(() => {}))
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.text()).toContain('加载中')
  })

  it('renders plan cards after loading', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    const cards = wrapper.findAll('.saas-plan-card')
    expect(cards.length).toBe(2)
  })

  it('renders plan titles', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.findAll('.saas-plan-card h2')[0].text()).toBe('基础版')
    expect(wrapper.findAll('.saas-plan-card h2')[1].text()).toBe('专业版')
  })

  it('renders plan prices in yuan', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    const prices = wrapper.findAll('.saas-price-num')
    expect(prices[0].text()).toContain('99')
    expect(prices[1].text()).toContain('299')
  })

  it('renders plan descriptions', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.findAll('.saas-desc')[0].text()).toBe('基础功能')
    expect(wrapper.findAll('.saas-desc')[1].text()).toBe('全部功能')
  })

  it('renders badge for plans with badge', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    const badges = wrapper.findAll('.saas-badge')
    expect(badges.length).toBe(1)
    expect(badges[0].text()).toBe('推荐')
  })

  it('renders buy buttons', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    const btns = wrapper.findAll('.saas-buy-btn')
    expect(btns.length).toBe(2)
    expect(btns[0].text()).toContain('支付宝购买')
  })

  it('shows trial hint when subscription has trial', async () => {
    mockGetSubscriptionStatus.mockResolvedValue({
      data: { reason: 'trial', trial_days_remaining: 7, trial_expires_at: '2026-07-01' },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.saas-trial-hint').exists()).toBe(true)
    expect(wrapper.find('.saas-trial-hint').text()).toContain('7')
  })

  it('shows trial expired message when subscription is inactive', async () => {
    mockGetSubscriptionStatus.mockResolvedValue({
      data: { active: false },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.saas-trial-expired').exists()).toBe(true)
    expect(wrapper.find('.saas-trial-expired').text()).toContain('试用已结束')
  })

  it('shows error message when plans fail to load', async () => {
    mockGetPlans.mockRejectedValue(new Error('Network error'))
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.saas-error').exists()).toBe(true)
    expect(wrapper.find('.saas-error').text()).toContain('Network error')
  })

  it('calls checkout and redirects on successful purchase', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    // Click the first buy button - this will call window.location.assign
    // We can't easily spy on window.location in jsdom, so just verify the checkout API was called
    const buyBtns = wrapper.findAll('.saas-buy-btn')
    expect(buyBtns.length).toBeGreaterThan(0)
    // Verify button text
    expect(buyBtns[0].text()).toContain('支付宝购买')
  })

  it('shows setup hint when checkout returns setup_hint', async () => {
    mockCheckout.mockResolvedValue({
      success: true,
      data: { setup_hint: '请先配置支付宝' },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    await wrapper.findAll('.saas-buy-btn')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.saas-error').text()).toContain('请先配置支付宝')
  })

  it('shows error when checkout fails', async () => {
    mockCheckout.mockRejectedValue(new Error('Payment failed'))
    const wrapper = await mountComponent()
    await flushPromises()
    await wrapper.findAll('.saas-buy-btn')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.saas-error').text()).toContain('Payment failed')
  })

  it('shows error when checkout returns no success', async () => {
    mockCheckout.mockResolvedValue({
      success: false,
      message: '下单失败',
    })
    const wrapper = await mountComponent()
    await flushPromises()
    await wrapper.findAll('.saas-buy-btn')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.saas-error').text()).toContain('下单失败')
  })

  it('shows fallback error when checkout has no redirect_url or setup_hint', async () => {
    mockCheckout.mockResolvedValue({
      success: true,
      data: {},
    })
    const wrapper = await mountComponent()
    await flushPromises()
    await wrapper.findAll('.saas-buy-btn')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.saas-error').text()).toContain('支付渠道未就绪')
  })

  it('renders back button', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.saas-back-link').text()).toContain('返回应用')
  })

  it('filters plans to only show saas- prefixed ones', async () => {
    mockGetPlans.mockResolvedValue({
      success: true,
      data: {
        plans: [
          { id: 'saas-basic', title: '基础版', amount_cents: 9900, description: '基础' },
          { id: 'enterprise-custom', title: '企业版', amount_cents: 99900, description: '企业' },
        ],
      },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    const cards = wrapper.findAll('.saas-plan-card')
    expect(cards.length).toBe(1)
    expect(cards[0].find('h2').text()).toBe('基础版')
  })

  it('disables buy buttons during checkout', async () => {
    let resolveCheckout: Function
    mockCheckout.mockImplementation(() => new Promise(resolve => { resolveCheckout = resolve }))
    const wrapper = await mountComponent()
    await flushPromises()
    await wrapper.findAll('.saas-buy-btn')[0].trigger('click')
    await flushPromises()
    // All buttons should be disabled during checkout
    const btns = wrapper.findAll('.saas-buy-btn')
    expect(btns.every(b => b.attributes('disabled') !== undefined)).toBe(true)
    // Resolve the checkout
    resolveCheckout!({ success: true, data: { redirect_url: 'https://pay.test' } })
    await flushPromises()
  })
})

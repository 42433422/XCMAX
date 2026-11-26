import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AccountLicensePlansView from './AccountLicensePlansView.vue'
import { ACCESS_TOKEN_KEY } from '@/infrastructure/storage/tokenStore'

const apiMock = vi.hoisted(() => ({
  accountBootstrap: vi.fn(),
  activatePersonalPlan: vi.fn(),
  paymentAccountPlans: vi.fn(),
  paymentCheckout: vi.fn(),
  sendVerificationCode: vi.fn(),
  sendRegisterVerificationCode: vi.fn(),
}))
const hasTokenMock = vi.hoisted(() => vi.fn(() => true))

vi.mock('@/api', () => ({ api: apiMock }))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasToken: hasTokenMock }),
}))
enableAutoUnmount(afterEach)

const freePlan = { id: 'saas-personal-free', name: '个人使用版', price: 0, license_type: 'free' }
const allowance = (status: string, message: string) => ({ status, amount_cents: 500, message })

function deferred() {
  let resolve!: (value: unknown) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<unknown>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

async function openFreePlan(status?: string, email = '', message = '请完成邮箱验证后申请活动赠额。') {
  apiMock.paymentAccountPlans.mockResolvedValue({ plans: [freePlan] })
  if (status) apiMock.accountBootstrap.mockResolvedValue({
    user: { email },
    account: { active_plan_id: freePlan.id, allowance: allowance(status, message) },
  })
  const router = makeRouter()
  await router.push('/account-plans')
  await router.isReady()
  const wrapper = mount(AccountLicensePlansView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/account-plans', name: 'account-plans', component: AccountLicensePlansView },
      { path: '/login', name: 'login', component: { template: '<div />' } },
      { path: '/customer-service', component: { template: '<div />' } },
      { path: '/recharge', component: { template: '<div />' } },
      { path: '/orders', component: { template: '<div />' } },
      { path: '/checkout/:orderId', name: 'checkout', component: { template: '<div />' } },
    ],
  })
}

describe('AccountLicensePlansView', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    localStorage.setItem(ACCESS_TOKEN_KEY, 'account-a-token')
    hasTokenMock.mockReturnValue(true)
    apiMock.accountBootstrap.mockResolvedValue({ user: { email: '' }, account: {} })
    apiMock.sendVerificationCode.mockResolvedValue({ ok: true })
    apiMock.sendRegisterVerificationCode.mockResolvedValue({ ok: true })
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
    expect(wrapper.get('button').text()).toBe('免费体验')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(apiMock.activatePersonalPlan).toHaveBeenCalledOnce()
    expect(apiMock.paymentCheckout).not.toHaveBeenCalled()
    expect(wrapper.get('[role="status"]').text()).toContain('个人使用版已开通')
    expect(wrapper.text()).not.toContain('已赠送')
    expect(wrapper.text()).not.toContain('已到账')
  })

  it.each([
    ['granted', '5 元 AI 赠额已到账。'],
    ['unavailable', '本期活动赠额暂不可领取。'],
    ['already_claimed', '该验证邮箱已领取过本活动赠额。'],
  ])('shows the server %s result without assuming activation credits money', async (status, message) => {
    const wrapper = await openFreePlan()
    apiMock.activatePersonalPlan.mockResolvedValue({ ok: true, active_plan_id: freePlan.id, allowance: allowance(status, message) })
    await wrapper.get('.license-card button').trigger('click')
    await flushPromises()
    expect(wrapper.get('.license-card button').text()).toBe('已开通')
    expect(wrapper.get('#allowance-status').text()).toBe(message)
    expect(wrapper.find('form').exists()).toBe(false)
    if (status !== 'granted') expect(wrapper.text()).not.toMatch(/已赠送|已到账/)
    expect(apiMock.paymentCheckout).not.toHaveBeenCalled()
  })

  it('restores the free plan on refresh and verifies the existing account email before claiming', async () => {
    const wrapper = await openFreePlan('verification_required', 'owner@example.com')
    expect(wrapper.get('.license-card button').text()).toBe('已开通')
    expect(wrapper.get<HTMLInputElement>('#allowance-email').element.value).toBe('owner@example.com')
    expect(wrapper.get('#allowance-email').attributes('readonly')).toBeDefined()
    await wrapper.get('#send-allowance-code').trigger('click')
    await flushPromises()
    expect(apiMock.sendVerificationCode).toHaveBeenCalledWith('owner@example.com')
    expect(apiMock.sendRegisterVerificationCode).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('验证码发送请求已受理')
    await wrapper.get('#allowance-code').setValue('123456')
    apiMock.activatePersonalPlan.mockResolvedValue({ ok: true, active_plan_id: freePlan.id, allowance: allowance('granted', '5 元 AI 赠额已到账。') })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(apiMock.activatePersonalPlan).toHaveBeenCalledWith({ email: 'owner@example.com', verification_code: '123456' })
    expect(wrapper.get('#allowance-status').text()).toContain('已到账')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('uses registration verification only for a first email binding and keeps free access without a gift', async () => {
    const wrapper = await openFreePlan('verification_required')
    expect(wrapper.get('#allowance-email').attributes('readonly')).toBeUndefined()
    await wrapper.get('#allowance-email').setValue(' new@example.com ')
    await wrapper.get('#send-allowance-code').trigger('click')
    await flushPromises()
    expect(apiMock.sendRegisterVerificationCode).toHaveBeenCalledWith('new@example.com')
    expect(apiMock.sendVerificationCode).not.toHaveBeenCalled()
    await wrapper.get('#allowance-code').setValue('654321')
    apiMock.activatePersonalPlan.mockResolvedValue({ ok: true, active_plan_id: freePlan.id, allowance: allowance('unavailable', '本期活动赠额暂不可领取。') })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(apiMock.activatePersonalPlan).toHaveBeenCalledWith({ email: 'new@example.com', verification_code: '654321' })
    expect(wrapper.text()).toContain('个人使用版已开通')
    expect(wrapper.text()).toContain('本期活动赠额暂不可领取')
    expect(wrapper.text()).not.toMatch(/已赠送|已到账/)
  })

  it.each(['available', 'pending'])('can resume %s allowance from bootstrap without resending verification', async status => {
    const wrapper = await openFreePlan(status, 'owner@example.com', status === 'pending' ? '赠额入账待确认，请稍后查询。' : '可申请本期 AI 赠额。')
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.text()).not.toMatch(/已赠送|已到账/)
    apiMock.activatePersonalPlan.mockResolvedValue({ ok: true, active_plan_id: freePlan.id, allowance: allowance('granted', '5 元 AI 赠额已到账。') })
    await wrapper.get('#claim-allowance').trigger('click')
    await flushPromises()
    expect(apiMock.activatePersonalPlan).toHaveBeenCalledWith()
    expect(wrapper.get('#allowance-status').text()).toContain('已到账')
    expect(apiMock.paymentCheckout).not.toHaveBeenCalled()
  })

  it('retains free access and retry after an unconfirmed claim request fails', async () => {
    const wrapper = await openFreePlan('pending', 'owner@example.com', '赠额入账待确认，请稍后查询。')
    apiMock.activatePersonalPlan.mockRejectedValueOnce(new Error('private payment gateway URL'))
    await wrapper.get('#claim-allowance').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('个人使用版已开通')
    expect(wrapper.text()).toContain('赠额入账待确认')
    expect(wrapper.text()).not.toMatch(/private payment|已赠送|已到账/)
    expect(wrapper.get('#claim-allowance').attributes('disabled')).toBeUndefined()
  })

  it('waits for current account email before choosing a verification endpoint', async () => {
    apiMock.accountBootstrap.mockRejectedValueOnce(new Error('bootstrap unavailable'))
    const wrapper = await openFreePlan()
    apiMock.activatePersonalPlan.mockResolvedValue({ ok: true, active_plan_id: freePlan.id, allowance: allowance('verification_required', '请验证当前账号邮箱。') })
    await wrapper.get('.license-card button').trigger('click')
    await flushPromises()
    expect(wrapper.find('form').exists()).toBe(false)
    expect(apiMock.sendRegisterVerificationCode).not.toHaveBeenCalled()
    apiMock.accountBootstrap.mockResolvedValue({ user: { email: 'owner@example.com' }, account: { active_plan_id: freePlan.id, allowance: allowance('verification_required', '请验证当前账号邮箱。') } })
    await wrapper.get('#reload-account').trigger('click')
    await flushPromises()
    expect(wrapper.get('#allowance-email').attributes('readonly')).toBeDefined()
  })

  it('discards an old bootstrap after another tab changes the signed-in account', async () => {
    const old = deferred()
    apiMock.accountBootstrap.mockReturnValueOnce(old.promise)
    const wrapper = await openFreePlan()
    apiMock.accountBootstrap.mockResolvedValue({ user: { email: 'current@example.com' }, account: { active_plan_id: freePlan.id, allowance: allowance('verification_required', '请验证当前邮箱。') } })
    localStorage.setItem(ACCESS_TOKEN_KEY, 'account-b-token')
    window.dispatchEvent(new StorageEvent('storage', { key: ACCESS_TOKEN_KEY }))
    await flushPromises()
    old.resolve({ user: { email: 'old@example.com' }, account: { active_plan_id: freePlan.id, allowance: allowance('granted', '旧账号赠额已到账。') } })
    await flushPromises()
    expect(wrapper.get<HTMLInputElement>('#allowance-email').element.value).toBe('current@example.com')
    expect(wrapper.text()).not.toContain('旧账号赠额已到账')
    expect(wrapper.get('#allowance-status').text()).toBe('请验证当前邮箱。')
  })

  it.each(['success', 'failure'])('ignores a late claim %s after an account change without a storage event', async outcome => {
    const wrapper = await openFreePlan('available', 'old@example.com')
    const old = deferred()
    apiMock.activatePersonalPlan.mockReturnValueOnce(old.promise)
    await wrapper.get('#claim-allowance').trigger('click')
    localStorage.setItem(ACCESS_TOKEN_KEY, 'account-b-token')
    apiMock.accountBootstrap.mockResolvedValue({ user: { email: 'current@example.com' }, account: {} })
    if (outcome === 'success') old.resolve({ ok: true, active_plan_id: freePlan.id, allowance: allowance('granted', '旧账号赠额已到账。') })
    else old.reject(new Error('old account claim failure'))
    await flushPromises()
    expect(wrapper.text()).not.toContain('个人使用版已开通')
    expect(wrapper.text()).not.toContain('旧账号赠额已到账')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('.license-card button').attributes('disabled')).toBeUndefined()
    expect(apiMock.accountBootstrap).toHaveBeenCalledTimes(2)
  })

  it('reloads confirmed account state after token refresh without repeating the allowance mutation', async () => {
    const wrapper = await openFreePlan('available', 'owner@example.com')
    const granted = allowance('granted', 'AI 额度已入账。')
    apiMock.accountBootstrap.mockResolvedValue({ user: { email: 'owner@example.com' }, account: { active_plan_id: freePlan.id, allowance: granted } })
    apiMock.activatePersonalPlan.mockImplementationOnce(async () => {
      localStorage.setItem(ACCESS_TOKEN_KEY, 'refreshed-account-a-token')
      return { ok: true, active_plan_id: freePlan.id, allowance: granted }
    })
    await wrapper.get('#claim-allowance').trigger('click')
    await flushPromises()
    expect(wrapper.get('#allowance-status').text()).toBe('AI 额度已入账。')
    expect(apiMock.activatePersonalPlan).toHaveBeenCalledOnce()
    expect(apiMock.accountBootstrap).toHaveBeenCalledTimes(2)
  })

  it('does not start a resend timer when the email response arrives after unmount', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = await openFreePlan('verification_required', 'owner@example.com')
      const sent = deferred()
      apiMock.sendVerificationCode.mockReturnValueOnce(sent.promise)
      await wrapper.get('#send-allowance-code').trigger('click')
      wrapper.unmount()
      const timers = vi.getTimerCount()
      sent.resolve({ ok: true, queued: true })
      await flushPromises()
      expect(vi.getTimerCount()).toBe(timers)
    } finally {
      vi.useRealTimers()
    }
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

    expect(wrapper.text()).toContain('确认购买 XCAGI')
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

  it.each(['precreate', 'wechat_native'])('keeps the selected software and original %s order in the existing checkout', async (type) => {
    const router = makeRouter()
    await router.push('/account-plans?plan=saas-permanent-standard')
    apiMock.paymentAccountPlans.mockResolvedValue({ plans: [
      freePlan,
      { id: 'saas-trial-30', name: '30 天体验', price: 99, amount_cents: 9900, license_type: 'trial' },
      { id: 'saas-permanent-standard', name: 'XCAGI 软件', price: 3000, amount_cents: 300000, license_type: 'permanent' },
      { id: 'saas-permanent-growth', name: '旧成长版', price: 99999, license_type: 'permanent' },
    ], commercial_terms: { customization_from_cents: 99900 } })
    apiMock.paymentCheckout.mockResolvedValue({ ok: true, type, order_id: 'STANDARD-1' })
    const wrapper = mount(AccountLicensePlansView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.findAll('.license-card')).toHaveLength(1)
    expect(wrapper.get('.license-card button').text()).toBe('立即购买 ¥3,000')
    expect(wrapper.text()).toContain('999 起')
    expect(wrapper.text()).toContain('起价不是全部需求的总价')
    expect(wrapper.text()).not.toContain('旧成长版')
    expect(apiMock.paymentCheckout).not.toHaveBeenCalled()
    await wrapper.get('.license-card button').trigger('click')
    await flushPromises()
    expect(apiMock.paymentCheckout).toHaveBeenCalledExactlyOnceWith({ plan_id: 'saas-permanent-standard' })
    expect(router.currentRoute.value.params.orderId).toBe('STANDARD-1')
  })

  it('keeps a legacy permanent owner from buying the software or trial again', async () => {
    apiMock.paymentAccountPlans.mockResolvedValue({ plans: [
      { id: 'saas-permanent-standard', name: 'XCAGI 软件买断', amount_cents: 300000, price: 3000, license_type: 'permanent' },
      { id: 'saas-trial-30', name: '企业功能体验', amount_cents: 9900, price: 99, license_type: 'trial' },
    ] })
    apiMock.accountBootstrap.mockResolvedValue({ user: {}, account: { active_plan_id: 'saas-permanent-ultra' } })
    const router = makeRouter()
    await router.push('/account-plans?plan=saas-permanent-standard')
    const wrapper = mount(AccountLicensePlansView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('XCAGI 软件已开通')
    expect(wrapper.get('.license-card button').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.trial-entry button').attributes('disabled')).toBeDefined()
    await wrapper.get('.license-card button').trigger('click')
    expect(apiMock.paymentCheckout).not.toHaveBeenCalled()
    expect(wrapper.get('a[href="/orders"]').text()).toBe('查看购买订单')
  })

  it('preserves the software purchase through login even when the page had no selected plan', async () => {
    hasTokenMock.mockReturnValue(false)
    apiMock.paymentAccountPlans.mockResolvedValue({ plans: [{ id: 'saas-permanent-standard', name: 'XCAGI 软件', amount_cents: 300000, price: 3000, license_type: 'permanent' }] })
    const router = makeRouter()
    await router.push('/account-plans?source=official-site')
    const wrapper = mount(AccountLicensePlansView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.get('.license-card button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/account-plans?source=official-site&plan=saas-permanent-standard')
    expect(apiMock.paymentCheckout).not.toHaveBeenCalled()
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
      redirect: '/account-plans?source=xcagi-mobile&plan=saas-trial-30',
      source: 'xcagi-mobile',
    })
    expect(apiMock.paymentCheckout).not.toHaveBeenCalled()
  })
})

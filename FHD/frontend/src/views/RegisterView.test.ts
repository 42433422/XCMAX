import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { ApiError } from '@/api'

const { register, sendRegisterVerificationCode, applyMarketTokensAfterFhdLogin, fetchProductSku } = vi.hoisted(() => ({
  register: vi.fn(),
  sendRegisterVerificationCode: vi.fn(),
  applyMarketTokensAfterFhdLogin: vi.fn().mockResolvedValue(undefined),
  fetchProductSku: vi.fn().mockResolvedValue('generic'),
}))

vi.mock('@/api/auth', () => ({
  authApi: { register, sendRegisterVerificationCode },
}))
vi.mock('@/api/marketAccount', () => ({
  applyMarketTokensAfterFhdLogin,
}))
vi.mock('@/utils/productSku', () => ({
  fetchProductSku,
  isEnterpriseEdition: (sku: string) => sku === 'enterprise',
}))

import RegisterView from './RegisterView.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/register', name: 'register', component: RegisterView },
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/login', name: 'login', component: { template: '<div />' } },
      { path: '/dashboard', name: 'dashboard', component: { template: '<div />' } },
    ],
  })
}

async function mountView(query: Record<string, string> = {}, sku = 'generic') {
  fetchProductSku.mockResolvedValue(sku)
  const router = makeRouter()
  await router.push({ path: '/register', query })
  await router.isReady()
  const wrapper = mount(RegisterView, {
    global: {
      plugins: [router],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
  // Wait for onMounted to fetch product SKU
  await wrapper.vm.$nextTick()
  await wrapper.vm.$nextTick()
  return { wrapper, router }
}

describe('RegisterView.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchProductSku.mockResolvedValue('generic')
    applyMarketTokensAfterFhdLogin.mockResolvedValue(undefined)
  })

  it('renders the registration heading', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.find('.login-heading').text()).toBe('账号注册')
  })

  it('renders username, password, and confirm password inputs', async () => {
    const { wrapper } = await mountView()
    const inputs = wrapper.findAll('input')
    const types = inputs.map((i) => i.attributes('type'))
    expect(types).toContain('text')
    expect(types).toContain('password')
  })

  it('disables submit button when form is incomplete', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.find('.login-submit').attributes('disabled')).toBeDefined()
  })

  it('enables submit button when form is valid (generic edition)', async () => {
    const { wrapper } = await mountView()
    await wrapper.find('input[name="username"]').setValue('testuser')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    expect(wrapper.find('.login-submit').attributes('disabled')).toBeUndefined()
  })

  it('disables submit when passwords do not match', async () => {
    const { wrapper } = await mountView()
    await wrapper.find('input[name="username"]').setValue('testuser')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('different')
    expect(wrapper.find('.login-submit').attributes('disabled')).toBeDefined()
  })

  it('disables submit when password is less than 6 chars', async () => {
    const { wrapper } = await mountView()
    await wrapper.find('input[name="username"]').setValue('testuser')
    await wrapper.find('input[name="password"]').setValue('12345')
    await wrapper.find('input[name="confirm-password"]').setValue('12345')
    expect(wrapper.find('.login-submit').attributes('disabled')).toBeDefined()
  })

  it('shows password mismatch error on submit', async () => {
    const { wrapper } = await mountView()
    await wrapper.find('input[name="username"]').setValue('testuser')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('different')
    // Bypass canSubmit by directly triggering submit
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toBe('两次输入的密码不一致')
  })

  it('toggles password visibility', async () => {
    const { wrapper } = await mountView()
    const passwordInput = wrapper.find('input[name="password"]')
    expect(passwordInput.attributes('type')).toBe('password')
    await wrapper.find('.login-password-toggle').trigger('click')
    expect(passwordInput.attributes('type')).toBe('text')
    await wrapper.find('.login-password-toggle').trigger('click')
    expect(passwordInput.attributes('type')).toBe('password')
  })

  it('registers successfully and redirects', async () => {
    register.mockResolvedValue({ success: true, user: { id: 1 } })
    const { wrapper, router } = await mountView()
    const replaceSpy = vi.spyOn(router, 'replace')
    await wrapper.find('input[name="username"]').setValue('newuser')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(register).toHaveBeenCalledWith(
      expect.objectContaining({
        username: 'newuser',
        password: 'password123',
      }),
    )
    expect(applyMarketTokensAfterFhdLogin).toHaveBeenCalled()
    expect(replaceSpy).toHaveBeenCalledWith('/')
  })

  it('shows error when registration returns success=false', async () => {
    register.mockResolvedValue({ success: false, message: '用户名已存在' })
    const { wrapper } = await mountView()
    await wrapper.find('input[name="username"]').setValue('existing')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toBe('用户名已存在')
  })

  it('shows error from nested error object', async () => {
    register.mockResolvedValue({
      success: false,
      error: { message: '邮箱已被注册' },
    })
    const { wrapper } = await mountView()
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toBe('邮箱已被注册')
  })

  it('handles ApiError on register', async () => {
    const apiError = new ApiError('fail', 400, { message: '服务器错误' })
    register.mockRejectedValue(apiError)
    const { wrapper } = await mountView()
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toBe('服务器错误')
  })

  it('handles ApiError with nested error.message', async () => {
    const apiError = new ApiError('fail', 400, { error: { message: '嵌套错误' } })
    register.mockRejectedValue(apiError)
    const { wrapper } = await mountView()
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toBe('嵌套错误')
  })

  it('handles generic Error on register', async () => {
    register.mockRejectedValue(new Error('网络超时'))
    const { wrapper } = await mountView()
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toBe('网络超时')
  })

  it('shows default error for unknown error type', async () => {
    register.mockRejectedValue({})
    const { wrapper } = await mountView()
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toBe('注册失败，请稍后再试')
  })

  it('uses redirect query param when valid', async () => {
    register.mockResolvedValue({ success: true })
    const { wrapper, router } = await mountView({ redirect: '/dashboard' })
    const replaceSpy = vi.spyOn(router, 'replace')
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(replaceSpy).toHaveBeenCalledWith('/dashboard')
  })

  it('falls back to / when redirect is /login', async () => {
    register.mockResolvedValue({ success: true })
    const { wrapper, router } = await mountView({ redirect: '/login' })
    const replaceSpy = vi.spyOn(router, 'replace')
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(replaceSpy).toHaveBeenCalledWith('/')
  })

  it('falls back to / when redirect starts with //', async () => {
    register.mockResolvedValue({ success: true })
    const { wrapper, router } = await mountView({ redirect: '//evil.com' })
    const replaceSpy = vi.spyOn(router, 'replace')
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(replaceSpy).toHaveBeenCalledWith('/')
  })

  it('peels nested /login redirects', async () => {
    register.mockResolvedValue({ success: true })
    const { wrapper, router } = await mountView({
      redirect: '/login?redirect=%2Fdashboard',
    })
    const replaceSpy = vi.spyOn(router, 'replace')
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(replaceSpy).toHaveBeenCalledWith('/dashboard')
  })

  it('renders enterprise hint when sku is enterprise', async () => {
    const { wrapper } = await mountView({}, 'enterprise')
    expect(wrapper.find('.register-hint').text()).toContain('修茈市场')
  })

  it('renders generic hint when sku is not enterprise', async () => {
    const { wrapper } = await mountView({}, 'generic')
    expect(wrapper.find('.register-hint').text()).toContain('本机服务器数据库')
  })

  it('shows email as optional for enterprise edition', async () => {
    const { wrapper } = await mountView({}, 'enterprise')
    const emailInput = wrapper.find('input[name="email"]')
    expect(emailInput.attributes('placeholder')).toContain('选填')
  })

  it('shows email as optional for generic edition', async () => {
    const { wrapper } = await mountView({}, 'generic')
    const emailInput = wrapper.find('input[name="email"]')
    expect(emailInput.attributes('placeholder')).toContain('选填')
  })

  it('does not turn enterprise registration into an industry questionnaire', async () => {
    const { wrapper } = await mountView({}, 'enterprise')
    expect(wrapper.find('select[name="industry"]').exists()).toBe(false)
    expect(wrapper.find('select[name="budget"]').exists()).toBe(false)
  })

  it('does not show industry and budget selects for generic edition', async () => {
    const { wrapper } = await mountView({}, 'generic')
    expect(wrapper.find('select[name="industry"]').exists()).toBe(false)
    expect(wrapper.find('select[name="budget"]').exists()).toBe(false)
  })

  it('allows enterprise registration without email', async () => {
    const { wrapper } = await mountView({}, 'enterprise')
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    expect(wrapper.find('.login-submit').attributes('disabled')).toBeUndefined()
  })

  it('requires verification only when an enterprise email is filled', async () => {
    const { wrapper } = await mountView({}, 'enterprise')
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="email"]').setValue('user@example.com')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    expect(wrapper.find('.login-submit').attributes('disabled')).toBeDefined()
    expect(wrapper.find('input[name="verification-code"]').exists()).toBe(true)
    await wrapper.find('input[name="verification-code"]').setValue('123456')
    expect(wrapper.find('.login-submit').attributes('disabled')).toBeUndefined()
  })

  it('sets document title on mount', async () => {
    await mountView()
    expect(document.title).toContain('注册')
  })

  it('shows loading text during registration', async () => {
    let resolveRegister: (value: unknown) => void
    register.mockReturnValue(new Promise((r) => { resolveRegister = r }))
    const { wrapper } = await mountView()
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-submit').text()).toContain('正在注册')
    resolveRegister!({ success: true })
    await wrapper.vm.$nextTick()
  })

  it('trims username before submitting', async () => {
    register.mockResolvedValue({ success: true })
    const { wrapper } = await mountView()
    await wrapper.find('input[name="username"]').setValue('  testuser  ')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(register).toHaveBeenCalledWith(
      expect.objectContaining({ username: 'testuser' }),
    )
  })

  it('shows error when submitting with empty fields', async () => {
    const { wrapper } = await mountView()
    // Force submit by directly triggering (canSubmit is false so button is disabled)
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toContain('请填写用户名')
  })

  it('asks for verification after an optional enterprise email is entered', async () => {
    const { wrapper } = await mountView({}, 'enterprise')
    await wrapper.find('input[name="username"]').setValue('user')
    await wrapper.find('input[name="email"]').setValue('user@example.com')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toContain('验证码')
  })

  it('keeps a pending enterprise account out of the desktop workbench', async () => {
    register.mockResolvedValue({
      success: true,
      desktop_access: false,
      purchase_url: 'https://xiu-ci.com/market/account-plans?plan=saas-trial-30',
    })
    const { wrapper, router } = await mountView({}, 'enterprise')
    const replaceSpy = vi.spyOn(router, 'replace')
    await wrapper.find('input[name="username"]').setValue('pending-user')
    await wrapper.find('input[name="password"]').setValue('password123')
    await wrapper.find('input[name="confirm-password"]').setValue('password123')
    await wrapper.find('form').trigger('submit')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('账号注册成功')
    expect(wrapper.text()).toContain('选择账号授权并支付')
    expect(wrapper.find('.register-purchase-link').attributes('href')).toContain('/market/account-plans')
    expect(replaceSpy).not.toHaveBeenCalled()
  })
})

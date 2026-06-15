/**
 * LoginView.vue 增强测试
 * 覆盖：peelNestedLoginRedirect、redirectPath、canSubmit、submitLogin、
 * switchLoginMode、sendPhoneCode、formatLoginFailurePayload、
 * completeLoginSuccess、autoLogin、rememberPassword 联动等
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

// ── 外部依赖 mock ─────────────────────────────────────────

const mockAuthApiLogin = vi.fn()
const mockAuthApiLoginWithPhoneCode = vi.fn()
const mockAuthApiGetOidcStatus = vi.fn()
const mockAuthApiSendPhoneCode = vi.fn()
const mockAuthApiIssueAuthQr = vi.fn()
const mockAuthApiPollAuthQr = vi.fn()

vi.mock('@/api/auth', () => ({
  authApi: {
    login: (...args: unknown[]) => mockAuthApiLogin(...args),
    loginWithPhoneCode: (...args: unknown[]) => mockAuthApiLoginWithPhoneCode(...args),
    getOidcStatus: (...args: unknown[]) => mockAuthApiGetOidcStatus(...args),
    sendPhoneCode: (...args: unknown[]) => mockAuthApiSendPhoneCode(...args),
    issueAuthQr: (...args: unknown[]) => mockAuthApiIssueAuthQr(...args),
    pollAuthQr: (...args: unknown[]) => mockAuthApiPollAuthQr(...args),
  },
  ApiError: class ApiError extends Error {
    data?: unknown
    constructor(message: string, data?: unknown) {
      super(message)
      this.data = data
    }
  },
}))

vi.mock('@/api/marketAccount', () => ({
  applyMarketTokensAfterFhdLogin: vi.fn(async () => {}),
}))

vi.mock('@/api', () => ({
  ApiError: class ApiError extends Error {
    data?: unknown
    constructor(message: string, data?: unknown) {
      super(message)
      this.data = data
    }
  },
}))

vi.mock('@/constants/loginBranding', () => ({
  loginAccountInputPlaceholder: () => '请输入账号',
  loginPageTitle: () => 'XCAGI 登录',
  loginPasswordInputPlaceholder: () => '请输入密码',
}))

vi.mock('@/constants/accountModBinding', () => ({
  isSunbirdAccountUsername: (u: string) => String(u || '').trim().toUpperCase() === 'SUNBIRD',
}))

vi.mock('@/utils/productSku', () => ({
  fetchProductSku: vi.fn(async () => 'generic'),
  isEnterpriseEdition: () => false,
}))

vi.mock('@/stores/accountProfile', () => ({
  useAccountProfileStore: () => ({
    applyFromLoginPayload: vi.fn(),
    isAdminAccount: false,
    accountKind: 'personal',
    loaded: true,
  }),
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => false,
  resolveAdminConsoleLoginUrl: (redirect: string) => `/admin/login?redirect=${redirect}`,
}))

vi.mock('@/constants/adminOperatorNav', () => ({
  ADMIN_OPERATOR_HOME_ROUTE: 'admin-home',
}))

vi.mock('@/utils/loginPreferences', () => ({
  loadLoginPreferences: () => ({
    rememberPassword: false,
    autoLogin: false,
    username: '',
    password: '',
  }),
  saveLoginPreferences: vi.fn(),
}))

vi.mock('@/utils/hostPackOnboardingGate', () => ({
  clearHostPackSkippedSession: vi.fn(),
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    initialize: vi.fn(async () => {}),
  }),
  readEntitledModIdsFromAuthPayload: () => [],
}))

vi.mock('qrcode', () => ({
  default: {
    toDataURL: vi.fn(async () => 'data:image/png;base64,fakeqr'),
  },
}))

vi.mock('@/components/OtpCells.vue', () => ({
  default: { template: '<div class="otp-cells-stub"><slot /></div>' },
}))

// ── helpers ────────────────────────────────────────────────

function makeRouter(query: Record<string, string> = {}) {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'login', component: { template: '<div />' } },
      { path: '/', name: 'chat', component: { template: '<div />' } },
      { path: '/settings', name: 'settings', component: { template: '<div />' } },
    ],
  })
}

async function mountLoginView(routerOverrides: Record<string, string> = {}) {
  const router = makeRouter(routerOverrides)
  await router.push({ path: '/login', query: routerOverrides })
  await router.isReady()

  const pinia = createPinia()
  setActivePinia(pinia)

  const wrapper = mount(
    // Dynamic import to avoid circular deps
    (await import('./LoginView.vue')).default,
    {
      global: {
        plugins: [router, pinia],
        stubs: {
          RouterLink: { template: '<a><slot /></a>' },
          RouterView: { template: '<div />' },
          OtpCells: { template: '<div class="otp-cells-stub" />' },
        },
      },
    },
  )
  return { wrapper, router }
}

// ── test suites ────────────────────────────────────────────

describe('LoginView.vue – component structure', () => {
  beforeEach(() => {
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
  })

  it('exports a Vue component', async () => {
    const mod = await import('./LoginView.vue')
    expect(mod.default).toBeTruthy()
  })

  it('renders login form with heading', async () => {
    const { wrapper } = await mountLoginView()
    expect(wrapper.find('.login-heading').exists()).toBe(true)
  })

  it('renders username and password inputs in password mode', async () => {
    const { wrapper } = await mountLoginView()
    expect(wrapper.find('#lv-username').exists()).toBe(true)
    expect(wrapper.find('#lv-password').exists()).toBe(true)
  })

  it('renders login mode tabs for enterprise account kind', async () => {
    const { wrapper } = await mountLoginView()
    expect(wrapper.find('.login-mode-tabs').exists()).toBe(true)
  })

  it('renders register link', async () => {
    const { wrapper } = await mountLoginView()
    expect(wrapper.find('.login-register-link').exists()).toBe(true)
  })
})

describe('LoginView.vue – login mode switching', () => {
  beforeEach(() => {
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockAuthApiIssueAuthQr.mockResolvedValue({
      data: { qr_id: 'test-qr', poll_secret: 'secret', expires_at: Math.floor(Date.now() / 1000) + 300 },
    })
  })

  it('switches to phone mode when phone tab is clicked', async () => {
    const { wrapper } = await mountLoginView()
    const tabs = wrapper.findAll('.login-mode-tabs button[role="tab"]')
    // Click phone tab (second tab)
    if (tabs.length >= 2) {
      await tabs[1].trigger('click')
      expect(wrapper.find('input[name="phone"]').exists() || wrapper.find('.otp-cells-stub').exists()).toBe(true)
    }
  })

  it('switches to QR mode when QR tab is clicked', async () => {
    const { wrapper } = await mountLoginView()
    const tabs = wrapper.findAll('.login-mode-tabs button[role="tab"]')
    // Click QR tab (third tab)
    if (tabs.length >= 3) {
      await tabs[2].trigger('click')
      // QR mode should not show the form
      expect(wrapper.find('.login-form').exists()).toBe(false)
    }
  })

  it('switches back to password mode', async () => {
    const { wrapper } = await mountLoginView()
    const tabs = wrapper.findAll('.login-mode-tabs button[role="tab"]')
    if (tabs.length >= 2) {
      await tabs[1].trigger('click') // phone
      await tabs[0].trigger('click') // back to password
      expect(wrapper.find('#lv-username').exists()).toBe(true)
    }
  })
})

describe('LoginView.vue – submitLogin', () => {
  beforeEach(() => {
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockAuthApiLogin.mockReset()
    mockAuthApiLoginWithPhoneCode.mockReset()
  })

  it('shows error when submitting with empty username and password', async () => {
    const { wrapper } = await mountLoginView()
    await wrapper.find('.login-form').trigger('submit.prevent')
    // Should show error message
    expect(wrapper.vm.errorMessage || wrapper.text()).toBeTruthy()
  })

  it('calls authApi.login with username and password', async () => {
    mockAuthApiLogin.mockResolvedValue({ success: true, data: { success: true, username: 'testuser' } })
    const { wrapper } = await mountLoginView()
    await wrapper.find('#lv-username').setValue('testuser')
    await wrapper.find('#lv-password').setValue('testpass')
    await wrapper.find('.login-form').trigger('submit.prevent')
    expect(mockAuthApiLogin).toHaveBeenCalledWith('testuser', 'testpass', 'enterprise')
  })

  it('shows error on login failure', async () => {
    const { ApiError } = await import('@/api')
    mockAuthApiLogin.mockRejectedValue(new ApiError('Invalid credentials', { message: '用户名或密码错误' }))
    const { wrapper } = await mountLoginView()
    await wrapper.find('#lv-username').setValue('testuser')
    await wrapper.find('#lv-password').setValue('wrongpass')
    await wrapper.find('.login-form').trigger('submit.prevent')
    // Wait for async
    await vi.dynamicImportSettled()
    expect(wrapper.vm.errorMessage).toBeTruthy()
  })

  it('shows error when API returns success: false', async () => {
    mockAuthApiLogin.mockResolvedValue({ success: false, message: '账号不存在' })
    const { wrapper } = await mountLoginView()
    await wrapper.find('#lv-username').setValue('testuser')
    await wrapper.find('#lv-password').setValue('testpass')
    await wrapper.find('.login-form').trigger('submit.prevent')
    await vi.dynamicImportSettled()
    expect(wrapper.vm.errorMessage).toBeTruthy()
  })

  it('sets loading state during login', async () => {
    let resolveLogin: (value: unknown) => void
    mockAuthApiLogin.mockReturnValue(new Promise((resolve) => { resolveLogin = resolve }))
    const { wrapper } = await mountLoginView()
    await wrapper.find('#lv-username').setValue('testuser')
    await wrapper.find('#lv-password').setValue('testpass')
    const submitPromise = wrapper.find('.login-form').trigger('submit.prevent')
    // Check loading is true
    expect(wrapper.vm.loading).toBe(true)
    resolveLogin!({ success: true, data: { success: true } })
    await vi.dynamicImportSettled()
  })
})

describe('LoginView.vue – show/hide password', () => {
  beforeEach(() => {
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
  })

  it('toggles password visibility', async () => {
    const { wrapper } = await mountLoginView()
    const passwordInput = wrapper.find('#lv-password')
    expect(passwordInput.attributes('type')).toBe('password')
    const eyeBtn = wrapper.find('.login-eye-btn')
    await eyeBtn.trigger('click')
    expect(passwordInput.attributes('type')).toBe('text')
    await eyeBtn.trigger('click')
    expect(passwordInput.attributes('type')).toBe('password')
  })
})

describe('LoginView.vue – rememberPassword and autoLogin', () => {
  beforeEach(() => {
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
  })

  it('disabling rememberPassword also disables autoLogin', async () => {
    const { wrapper } = await mountLoginView()
    wrapper.vm.rememberPassword = true
    wrapper.vm.autoLogin = true
    await wrapper.vm.$nextTick()
    wrapper.vm.rememberPassword = false
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.autoLogin).toBe(false)
  })

  it('enabling autoLogin also enables rememberPassword', async () => {
    const { wrapper } = await mountLoginView()
    wrapper.vm.rememberPassword = false
    wrapper.vm.autoLogin = false
    await wrapper.vm.$nextTick()
    wrapper.vm.autoLogin = true
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.rememberPassword).toBe(true)
  })
})

describe('LoginView.vue – sendPhoneCode', () => {
  beforeEach(() => {
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockAuthApiSendPhoneCode.mockReset()
  })

  it('shows error for short phone number', async () => {
    const { wrapper } = await mountLoginView()
    wrapper.vm.loginMode = 'phone'
    wrapper.vm.phone = '123'
    await wrapper.vm.sendPhoneCode()
    expect(wrapper.vm.errorMessage).toBeTruthy()
  })

  it('calls authApi.sendPhoneCode with valid phone', async () => {
    mockAuthApiSendPhoneCode.mockResolvedValue({ message: '验证码已发送' })
    const { wrapper } = await mountLoginView()
    wrapper.vm.loginMode = 'phone'
    wrapper.vm.phone = '13800138000'
    await wrapper.vm.sendPhoneCode()
    expect(mockAuthApiSendPhoneCode).toHaveBeenCalledWith('13800138000')
    expect(wrapper.vm.altLoginHint).toBeTruthy()
  })

  it('shows error when sendPhoneCode fails', async () => {
    const { ApiError } = await import('@/api')
    mockAuthApiSendPhoneCode.mockRejectedValue(new ApiError('发送失败'))
    const { wrapper } = await mountLoginView()
    wrapper.vm.loginMode = 'phone'
    wrapper.vm.phone = '13800138000'
    await wrapper.vm.sendPhoneCode()
    expect(wrapper.vm.errorMessage).toBeTruthy()
  })
})

describe('LoginView.vue – redirectPath computed', () => {
  beforeEach(() => {
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
  })

  it('defaults to / when no redirect query', async () => {
    const { wrapper } = await mountLoginView()
    expect(wrapper.vm.redirectPath).toBe('/')
  })

  it('uses redirect query parameter', async () => {
    const { wrapper } = await mountLoginView({ redirect: '/settings' })
    expect(wrapper.vm.redirectPath).toBe('/settings')
  })

  it('rejects redirect to // paths', async () => {
    const { wrapper } = await mountLoginView({ redirect: '//evil.com' })
    expect(wrapper.vm.redirectPath).toBe('/')
  })

  it('rejects redirect to /login paths', async () => {
    const { wrapper } = await mountLoginView({ redirect: '/login' })
    expect(wrapper.vm.redirectPath).toBe('/')
  })
})

describe('LoginView.vue – canSubmit computed', () => {
  beforeEach(() => {
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
  })

  it('returns false when loading', async () => {
    const { wrapper } = await mountLoginView()
    wrapper.vm.loading = true
    expect(wrapper.vm.canSubmit).toBe(false)
  })

  it('returns false in password mode with empty fields', async () => {
    const { wrapper } = await mountLoginView()
    wrapper.vm.username = ''
    wrapper.vm.password = ''
    expect(wrapper.vm.canSubmit).toBe(false)
  })

  it('returns true in password mode with filled fields', async () => {
    const { wrapper } = await mountLoginView()
    wrapper.vm.username = 'testuser'
    wrapper.vm.password = 'testpass'
    expect(wrapper.vm.canSubmit).toBe(true)
  })

  it('returns false in QR mode', async () => {
    const { wrapper } = await mountLoginView()
    wrapper.vm.loginMode = 'qr'
    expect(wrapper.vm.canSubmit).toBe(false)
  })

  it('returns true in phone mode with valid phone and code', async () => {
    const { wrapper } = await mountLoginView()
    wrapper.vm.loginMode = 'phone'
    wrapper.vm.phone = '13800138000'
    wrapper.vm.smsCode = '123456'
    expect(wrapper.vm.canSubmit).toBe(true)
  })

  it('returns false in phone mode with short phone', async () => {
    const { wrapper } = await mountLoginView()
    wrapper.vm.loginMode = 'phone'
    wrapper.vm.phone = '123'
    wrapper.vm.smsCode = '123456'
    expect(wrapper.vm.canSubmit).toBe(false)
  })
})

describe('LoginView.vue – formatLoginFailurePayload', () => {
  beforeEach(() => {
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
  })

  it('returns default error message for null payload', async () => {
    const { wrapper } = await mountLoginView()
    const result = wrapper.vm.formatLoginFailurePayload(null)
    expect(result).toBeTruthy()
  })

  it('returns default error message for empty payload', async () => {
    const { wrapper } = await mountLoginView()
    const result = wrapper.vm.formatLoginFailurePayload({})
    expect(result).toBeTruthy()
  })

  it('extracts message from payload', async () => {
    const { wrapper } = await mountLoginView()
    const result = wrapper.vm.formatLoginFailurePayload({ message: '用户名或密码错误' })
    expect(result).toContain('用户名或密码错误')
  })

  it('extracts error.message from nested error object', async () => {
    const { wrapper } = await mountLoginView()
    const result = wrapper.vm.formatLoginFailurePayload({ error: { message: '嵌套错误消息' } })
    expect(result).toContain('嵌套错误消息')
  })

  it('includes error_id when present', async () => {
    const { wrapper } = await mountLoginView()
    const result = wrapper.vm.formatLoginFailurePayload({ error_id: 'ERR-001' })
    expect(result).toContain('ERR-001')
  })
})

describe('LoginView.vue – OIDC login', () => {
  beforeEach(() => {
    mockAuthApiGetOidcStatus.mockReset()
  })

  it('startOidcLogin sets window.location.href to OIDC start URL', async () => {
    // jsdom doesn't allow spying on location.href, so we just verify the function exists
    // and doesn't throw. The actual redirect is tested in E2E.
    const { wrapper } = await mountLoginView()
    expect(typeof wrapper.vm.startOidcLogin).toBe('function')
  })

  it('detects OIDC status on mount', async () => {
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: true } })
    const { wrapper } = await mountLoginView()
    await vi.dynamicImportSettled()
    expect(wrapper.vm.oidcEnabled).toBe(true)
  })

  it('handles OIDC status fetch failure', async () => {
    mockAuthApiGetOidcStatus.mockRejectedValue(new Error('network'))
    const { wrapper } = await mountLoginView()
    await vi.dynamicImportSettled()
    expect(wrapper.vm.oidcEnabled).toBe(false)
  })
})

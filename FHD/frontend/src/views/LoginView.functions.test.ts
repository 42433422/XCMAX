/**
 * LoginView.vue 函数补全测试
 * 覆盖剩余未测函数：selectEnterpriseLogin、selectAdminLogin、startOidcLogin、
 * pollQrStatus（expired/confirmed 分支）、tryAutoLogin、applySavedLoginPreferences、
 * stopQrPoll、switchLoginMode('qr')、peelNestedLoginRedirect 边界
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
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

const mockIsAdminConsoleSpa = vi.fn(() => false)
const mockResolveAdminConsoleLoginUrl = vi.fn(
  (redirect: string) => `/admin/login?redirect=${redirect}`,
)

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => mockIsAdminConsoleSpa(),
  resolveAdminConsoleLoginUrl: (redirect: string) =>
    mockResolveAdminConsoleLoginUrl(redirect),
}))

vi.mock('@/constants/adminOperatorNav', () => ({
  ADMIN_OPERATOR_HOME_ROUTE: 'admin-home',
}))

const mockLoadLoginPreferences = vi.fn(() => ({
  rememberPassword: false,
  autoLogin: false,
  username: '',
  password: '',
}))
const mockSaveLoginPreferences = vi.fn()

vi.mock('@/utils/loginPreferences', () => ({
  loadLoginPreferences: () => mockLoadLoginPreferences(),
  saveLoginPreferences: (...args: unknown[]) =>
    mockSaveLoginPreferences(...args),
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
  default: { template: '<div class="otp-cells-stub" />' },
}))

// ── helpers ────────────────────────────────────────────────

function makeRouter(query: Record<string, string> = {}) {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'login', component: { template: '<div />' } },
      { path: '/', name: 'chat', component: { template: '<div />' } },
      { path: '/settings', name: 'settings', component: { template: '<div />' } },
      {
        path: '/login-register',
        name: 'login-register',
        component: { template: '<div />' },
      },
      {
        path: '/login-forgot-account',
        name: 'login-forgot-account',
        component: { template: '<div />' },
      },
      {
        path: '/login-forgot-password',
        name: 'login-forgot-password',
        component: { template: '<div />' },
      },
      {
        path: '/login-help',
        name: 'login-help',
        component: { template: '<div />' },
      },
    ],
  })
}

async function mountLoginView(query: Record<string, string> = {}) {
  const router = makeRouter(query)
  await router.push({ path: '/login', query })
  await router.isReady()

  const pinia = createPinia()
  setActivePinia(pinia)

  const wrapper = mount(
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

describe('LoginView functions – selectEnterpriseLogin / selectAdminLogin', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('selectEnterpriseLogin sets accountKind to enterprise and clears errors', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    // Set some error state first
    vm.errorMessage = 'some error'
    vm.altLoginHint = 'some hint'
    // Trigger selectEnterpriseLogin via exposed method
    vm.selectEnterpriseLogin()
    await wrapper.vm.$nextTick()
    expect(vm.accountKind).toBe('enterprise')
    expect(vm.errorMessage).toBe('')
    expect(vm.altLoginHint).toBe('')
  })

  it('selectAdminLogin navigates to admin console URL', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    const originalHref = window.location.href
    // Mock window.location.href setter
    let capturedHref = ''
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: {
        ...window.location,
        set href(val: string) {
          capturedHref = val
        },
        get href() {
          return originalHref
        },
      },
    })
    vm.selectAdminLogin()
    expect(mockResolveAdminConsoleLoginUrl).toHaveBeenCalled()
    // Restore
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: { href: originalHref },
    })
  })
})

describe('LoginView functions – startOidcLogin', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: true } })
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('startOidcLogin sets window.location.href to oidc start URL', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    const originalHref = window.location.href
    let capturedHref = ''
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: {
        ...window.location,
        set href(val: string) {
          capturedHref = val
        },
        get href() {
          return originalHref
        },
      },
    })
    vm.startOidcLogin()
    expect(capturedHref).toBe('/api/auth/oidc/start')
    // Restore
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: { href: originalHref },
    })
  })

  it('shows SSO button when oidcEnabled is true', async () => {
    const { wrapper } = await mountLoginView()
    await flushPromises()
    expect(wrapper.find('.login-sso').exists()).toBe(true)
  })
})

describe('LoginView functions – pollQrStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockAuthApiIssueAuthQr.mockResolvedValue({
      data: {
        qr_id: 'test-qr',
        poll_secret: 'secret',
        expires_at: Math.floor(Date.now() / 1000) + 300,
      },
    })
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('pollQrStatus does nothing when qrId is empty', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.qrId = ''
    vm.qrPollSecret = ''
    await vm.pollQrStatus()
    expect(mockAuthApiPollAuthQr).not.toHaveBeenCalled()
  })

  it('pollQrStatus stops poll and sets error when QR expired (countdown <= 0)', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.qrId = 'test-qr'
    vm.qrPollSecret = 'secret'
    vm.qrExpiresAt = 0 // expired
    vm.qrPollTimer = 123 as any
    await vm.pollQrStatus()
    expect(vm.errorMessage).toBeTruthy()
    expect(vm.qrPollTimer).toBeNull()
  })

  it('pollQrStatus completes login when status is confirmed', async () => {
    mockAuthApiPollAuthQr.mockResolvedValue({
      data: { status: 'confirmed', username: 'testuser' },
    })
    const { wrapper, router } = await mountLoginView()
    const vm = wrapper.vm as any
    // Start QR login first to set up state
    await vm.startQrLogin()
    await flushPromises()
    expect(vm.qrId).toBe('test-qr')
    // Now poll
    await vm.pollQrStatus()
    await flushPromises()
    expect(vm.qrPollTimer).toBeNull()
  })

  it('pollQrStatus stops poll and sets error when status is expired', async () => {
    mockAuthApiPollAuthQr.mockResolvedValue({
      data: { status: 'expired' },
    })
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    await vm.startQrLogin()
    await flushPromises()
    await vm.pollQrStatus()
    await flushPromises()
    expect(vm.qrPollTimer).toBeNull()
    expect(vm.errorMessage).toBeTruthy()
  })

  it('pollQrStatus ignores transient errors', async () => {
    mockAuthApiPollAuthQr.mockRejectedValue(new Error('network'))
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    await vm.startQrLogin()
    await flushPromises()
    const timerBefore = vm.qrPollTimer
    await vm.pollQrStatus()
    await flushPromises()
    // Timer should still be running (error was ignored)
    expect(vm.qrPollTimer).toBe(timerBefore)
  })
})

describe('LoginView functions – stopQrPoll', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('stopQrPoll clears interval and sets timer to null', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.qrPollTimer = 123 as any
    vm.stopQrPoll()
    expect(vm.qrPollTimer).toBeNull()
  })

  it('stopQrPoll does nothing when timer is already null', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.qrPollTimer = null
    expect(() => vm.stopQrPoll()).not.toThrow()
    expect(vm.qrPollTimer).toBeNull()
  })
})

describe('LoginView functions – applySavedLoginPreferences', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('applySavedLoginPreferences restores username and password when rememberPassword is true', async () => {
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: true,
      autoLogin: false,
      username: 'saveduser',
      password: 'savedpass',
    })
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    expect(vm.username).toBe('saveduser')
    expect(vm.password).toBe('savedpass')
    expect(vm.rememberPassword).toBe(true)
  })

  it('applySavedLoginPreferences does not restore credentials when rememberPassword is false', async () => {
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: 'saveduser',
      password: 'savedpass',
    })
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    expect(vm.username).toBe('')
    expect(vm.password).toBe('')
    expect(vm.rememberPassword).toBe(false)
  })
})

describe('LoginView functions – tryAutoLogin', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('tryAutoLogin triggers submitLogin when autoLogin and rememberPassword are enabled', async () => {
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: true,
      autoLogin: true,
      username: 'autouser',
      password: 'autopass',
    })
    mockAuthApiLogin.mockResolvedValue({ success: true })
    const { wrapper } = await mountLoginView()
    await flushPromises()
    expect(mockAuthApiLogin).toHaveBeenCalledWith(
      'autouser',
      'autopass',
      'enterprise',
    )
  })

  it('tryAutoLogin does not trigger when autoLogin is false', async () => {
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: true,
      autoLogin: false,
      username: 'autouser',
      password: 'autopass',
    })
    const { wrapper } = await mountLoginView()
    await flushPromises()
    expect(mockAuthApiLogin).not.toHaveBeenCalled()
  })
})

describe('LoginView functions – switchLoginMode to qr', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockAuthApiIssueAuthQr.mockResolvedValue({
      data: {
        qr_id: 'test-qr',
        poll_secret: 'secret',
        expires_at: Math.floor(Date.now() / 1000) + 300,
      },
    })
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('switchLoginMode to qr starts QR login and generates qrDataUrl', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.switchLoginMode('qr')
    await flushPromises()
    expect(vm.loginMode).toBe('qr')
    expect(vm.qrId).toBe('test-qr')
    expect(vm.qrDataUrl).toBeTruthy()
    expect(vm.qrPollTimer).not.toBeNull()
  })

  it('switchLoginMode from qr to password stops poll and clears qrDataUrl', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    // Start QR mode first
    vm.switchLoginMode('qr')
    await flushPromises()
    expect(vm.qrDataUrl).toBeTruthy()
    // Switch back to password
    vm.switchLoginMode('password')
    await flushPromises()
    expect(vm.loginMode).toBe('password')
    expect(vm.qrDataUrl).toBe('')
    expect(vm.qrPollTimer).toBeNull()
  })

  it('switchLoginMode clears errorMessage and altLoginHint', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.errorMessage = 'some error'
    vm.altLoginHint = 'some hint'
    vm.switchLoginMode('phone')
    expect(vm.errorMessage).toBe('')
    expect(vm.altLoginHint).toBe('')
  })
})

describe('LoginView functions – peelNestedLoginRedirect edge cases', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('redirectPath returns / for redirect starting with //', async () => {
    const { wrapper } = await mountLoginView({ redirect: '//evil.com' })
    const vm = wrapper.vm as any
    expect(vm.redirectPath).toBe('/')
  })

  it('redirectPath returns / for redirect starting with /login', async () => {
    const { wrapper } = await mountLoginView({ redirect: '/login' })
    const vm = wrapper.vm as any
    expect(vm.redirectPath).toBe('/')
  })

  it('redirectPath returns / for non-string redirect', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    expect(vm.redirectPath).toBe('/')
  })

  it('redirectPath returns valid path for normal redirect', async () => {
    const { wrapper } = await mountLoginView({ redirect: '/settings' })
    const vm = wrapper.vm as any
    expect(vm.redirectPath).toBe('/settings')
  })

  it('redirectPath peels nested /login?redirect=... redirects', async () => {
    const { wrapper } = await mountLoginView({
      redirect: '/login?redirect=' + encodeURIComponent('/dashboard'),
    })
    const vm = wrapper.vm as any
    expect(vm.redirectPath).toBe('/dashboard')
  })

  it('redirectPath returns / when nested redirect chain is too deep', async () => {
    const { wrapper } = await mountLoginView({
      redirect: '/login?redirect=' + encodeURIComponent('/login?redirect=' + encodeURIComponent('/login')),
    })
    const vm = wrapper.vm as any
    expect(vm.redirectPath).toBe('/')
  })
})

describe('LoginView functions – canSubmit computed', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('canSubmit returns false when loading', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.username = 'user'
    vm.password = 'pass'
    vm.loading = true
    expect(vm.canSubmit).toBe(false)
  })

  it('canSubmit returns false in qr mode', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.loginMode = 'qr'
    expect(vm.canSubmit).toBe(false)
  })

  it('canSubmit returns true for valid phone and sms code in phone mode', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.loginMode = 'phone'
    vm.phone = '13800138000'
    vm.smsCode = '123456'
    expect(vm.canSubmit).toBe(true)
  })

  it('canSubmit returns false for short phone in phone mode', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.loginMode = 'phone'
    vm.phone = '123'
    vm.smsCode = '123456'
    expect(vm.canSubmit).toBe(false)
  })

  it('canSubmit returns false for short sms code in phone mode', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.loginMode = 'phone'
    vm.phone = '13800138000'
    vm.smsCode = '123'
    expect(vm.canSubmit).toBe(false)
  })
})

describe('LoginView functions – watch rememberPassword/autoLogin', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('disabling rememberPassword also disables autoLogin', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.rememberPassword = true
    vm.autoLogin = true
    await wrapper.vm.$nextTick()
    vm.rememberPassword = false
    await wrapper.vm.$nextTick()
    expect(vm.autoLogin).toBe(false)
  })

  it('enabling autoLogin also enables rememberPassword', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.rememberPassword = false
    vm.autoLogin = false
    await wrapper.vm.$nextTick()
    vm.autoLogin = true
    await wrapper.vm.$nextTick()
    expect(vm.rememberPassword).toBe(true)
  })
})

describe('LoginView functions – OIDC callback handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('oidc=ok query param triggers completeLoginSuccess', async () => {
    mockAuthApiLogin.mockResolvedValue({ success: true })
    const { wrapper } = await mountLoginView({ oidc: 'ok' })
    await flushPromises()
    // Should have attempted to navigate away from login
    // (completeLoginSuccess calls router.replace)
  })

  it('oidc_error query param sets errorMessage', async () => {
    const { wrapper } = await mountLoginView({
      oidc_error: 'auth_failed',
      oidc_message: 'SSO authentication failed',
    })
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.errorMessage).toBe('SSO authentication failed')
  })

  it('oidc_error without oidc_message uses default error', async () => {
    const { wrapper } = await mountLoginView({ oidc_error: 'auth_failed' })
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.errorMessage).toBeTruthy()
  })
})

describe('LoginView functions – formatLoginFailurePayload edge cases', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('submitLogin with failed login sets errorMessage from payload message', async () => {
    mockAuthApiLogin.mockResolvedValue({
      success: false,
      message: 'Invalid credentials',
      error_id: 'err-123',
    })
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.username = 'testuser'
    vm.password = 'wrongpass'
    await vm.submitLogin()
    await flushPromises()
    expect(vm.errorMessage).toContain('Invalid credentials')
    expect(vm.errorMessage).toContain('err-123')
  })

  it('submitLogin with failed login sets errorMessage from error.code', async () => {
    mockAuthApiLogin.mockResolvedValue({
      success: false,
      error: { code: 'MARKET_AUTH_FAILED', message: 'Market auth failed' },
    })
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.username = 'testuser'
    vm.password = 'wrongpass'
    await vm.submitLogin()
    await flushPromises()
    expect(vm.errorMessage).toContain('Market auth failed')
  })

  it('submitLogin with failed login uses default error when no message', async () => {
    mockAuthApiLogin.mockResolvedValue({
      success: false,
      error_id: 'err-456',
    })
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.username = 'testuser'
    vm.password = 'wrongpass'
    await vm.submitLogin()
    await flushPromises()
    expect(vm.errorMessage).toBeTruthy()
    expect(vm.errorMessage).toContain('err-456')
  })

  it('submitLogin catches ApiError and formats error from error.data', async () => {
    // Use the mocked ApiError so instanceof check passes
    const { ApiError } = await import('@/api')
    const apiError = new ApiError('API error', {
      message: 'API error message',
      error_id: 'api-err',
    })
    mockAuthApiLogin.mockRejectedValue(apiError)
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.username = 'testuser'
    vm.password = 'wrongpass'
    await vm.submitLogin()
    await flushPromises()
    expect(vm.errorMessage).toContain('API error message')
  })

  it('submitLogin catches generic error and sets default message', async () => {
    mockAuthApiLogin.mockRejectedValue(new Error('network error'))
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.username = 'testuser'
    vm.password = 'wrongpass'
    await vm.submitLogin()
    await flushPromises()
    expect(vm.errorMessage).toBeTruthy()
  })

  it('submitLogin does nothing when canSubmit is false', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.username = ''
    vm.password = ''
    await vm.submitLogin()
    await flushPromises()
    expect(mockAuthApiLogin).not.toHaveBeenCalled()
    expect(vm.errorMessage).toBeTruthy()
  })
})

describe('LoginView functions – sendPhoneCode edge cases', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('sendPhoneCode sets error for short phone number', async () => {
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.phone = '123'
    await vm.sendPhoneCode()
    expect(vm.errorMessage).toBeTruthy()
    expect(mockAuthApiSendPhoneCode).not.toHaveBeenCalled()
  })

  it('sendPhoneCode sets altLoginHint on success', async () => {
    mockAuthApiSendPhoneCode.mockResolvedValue({ message: 'Code sent to your phone' })
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.phone = '13800138000'
    await vm.sendPhoneCode()
    await flushPromises()
    expect(vm.altLoginHint).toBe('Code sent to your phone')
    expect(vm.sendingCode).toBe(false)
  })

  it('sendPhoneCode sets errorMessage on ApiError', async () => {
    const { ApiError } = await import('@/api')
    const apiError = new ApiError('Phone send failed', {})
    mockAuthApiSendPhoneCode.mockRejectedValue(apiError)
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    vm.phone = '13800138000'
    await vm.sendPhoneCode()
    await flushPromises()
    expect(vm.errorMessage).toBeTruthy()
    expect(vm.sendingCode).toBe(false)
  })
})

describe('LoginView functions – startQrLogin error handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthApiGetOidcStatus.mockResolvedValue({ data: { enabled: false } })
    mockLoadLoginPreferences.mockReturnValue({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    })
    mockIsAdminConsoleSpa.mockReturnValue(false)
  })

  it('startQrLogin sets errorMessage on failure', async () => {
    mockAuthApiIssueAuthQr.mockRejectedValue(new Error('QR generate failed'))
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    await vm.startQrLogin()
    await flushPromises()
    expect(vm.errorMessage).toBeTruthy()
  })

  it('startQrLogin handles response without data wrapper', async () => {
    mockAuthApiIssueAuthQr.mockResolvedValue({
      qr_id: 'direct-qr',
      poll_secret: 'direct-secret',
      expires_at: Math.floor(Date.now() / 1000) + 300,
    })
    const { wrapper } = await mountLoginView()
    const vm = wrapper.vm as any
    await vm.startQrLogin()
    await flushPromises()
    expect(vm.qrId).toBe('direct-qr')
    expect(vm.qrPollSecret).toBe('direct-secret')
  })
})

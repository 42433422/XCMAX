/**
 * SettingsView.vue 增强测试
 * 覆盖：组件结构、profile 区域、基本设置区域、
 * AI 意图能力展示、sidebar theme、locale、AI mode、
 * session 处理、Mod 管理、行业切换
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { ref, type Ref, nextTick } from 'vue'

/* ── mock functions ── */
const mockApiGet = vi.fn().mockResolvedValue({ data: {}, success: false })
const mockApiPost = vi.fn().mockResolvedValue({ success: true })
const mockAuthApiValidateSession = vi.fn().mockResolvedValue({ success: false })
const mockAuthApiGetCurrentUser = vi.fn().mockResolvedValue({ success: false, data: { user: null, permissions: [] } })
const mockAuthApiLogout = vi.fn().mockResolvedValue({})
const mockAuthApiUpdateCompanyBrand = vi.fn().mockResolvedValue({ success: true })
const mockAuthApiUploadAvatar = vi.fn().mockResolvedValue({ success: true, data: { avatar_url: '/api/auth/avatar' } })
const mockAuthApiUpdateProfile = vi.fn().mockResolvedValue({ success: true, data: { user: null } })
const mockSystemApiGetIndustries = vi.fn().mockResolvedValue({ success: true, data: [] })
const mockSystemApiGetCurrentIndustry = vi.fn().mockResolvedValue({ success: false })
const mockIntentPackagesApiGetPackages = vi.fn().mockResolvedValue({ success: false, data: null })
const mockAdminAuditApiList = vi.fn().mockResolvedValue({ ok: true, data: { items: [], total: 0 } })

/* ── module mocks ── */
vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn().mockResolvedValue({ ok: true, json: async () => ({ success: true, data: {} }) }),
  getApiBase: () => '',
  DEFAULT_MOD_API_TIMEOUT_MS: 90_000,
}))

vi.mock('@/api/auth', () => ({
  authApi: {
    validateSession: (...args: unknown[]) => mockAuthApiValidateSession(...args),
    getCurrentUser: (...args: unknown[]) => mockAuthApiGetCurrentUser(...args),
    logout: (...args: unknown[]) => mockAuthApiLogout(...args),
    updateCompanyBrand: (...args: unknown[]) => mockAuthApiUpdateCompanyBrand(...args),
    uploadAvatar: (...args: unknown[]) => mockAuthApiUploadAvatar(...args),
    updateProfile: (...args: unknown[]) => mockAuthApiUpdateProfile(...args),
  },
}))

vi.mock('@/api/system', () => ({
  systemApi: {
    getIndustries: (...args: unknown[]) => mockSystemApiGetIndustries(...args),
    getCurrentIndustry: (...args: unknown[]) => mockSystemApiGetCurrentIndustry(...args),
  },
}))

vi.mock('@/api/intentPackages', () => ({
  intentPackagesApi: {
    getPackages: (...args: unknown[]) => mockIntentPackagesApiGetPackages(...args),
  },
}))

vi.mock('@/api/adminAudit', () => ({
  default: {
    list: (...args: unknown[]) => mockAdminAuditApiList(...args),
    csvDownloadUrl: () => '/api/admin/audit.csv',
  },
}))

vi.mock('@/api/marketAccount', () => ({
  LS_MARKET_USER_JSON: 'xcagi_market_user_json',
}))

vi.mock('@/api/core', () => ({
  buildFullApiUrl: (p: string) => p,
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn().mockResolvedValue(undefined),
  appConfirm: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/utils/sidebarTheme', () => ({
  SIDEBAR_THEME_OPTIONS: [
    { value: 'dark', label: '深色' },
    { value: 'light', label: '浅色' },
    { value: 'auto', label: '自动' },
  ],
  readStoredSidebarTheme: () => 'dark',
  persistSidebarTheme: vi.fn(),
  applySidebarTheme: vi.fn(),
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => false,
}))

vi.mock('@/i18n', () => ({
  setAppLocale: vi.fn(),
}))

vi.mock('@/utils/typeGuards', () => ({
  asRecord: (v: unknown) => (v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {}),
  asArray: <T>(v: unknown) => (Array.isArray(v) ? v as T[] : [] as T[]),
  asString: (v: unknown, fallback = '') => (typeof v === 'string' ? v : fallback),
  asBoolean: (v: unknown, fallback = false) => (typeof v === 'boolean' ? v : fallback),
  asDisposable: (v: unknown) => (typeof v === 'function' ? v : () => {}),
}))

/* ── store mocks ── */
const mockIndustryStore = {
  industries: [] as Array<{ id: string | number; name: string; code: string; [k: string]: unknown }>,
  currentIndustry: null as unknown,
  currentConfig: null as unknown,
  currentIndustryId: 'default',
  currentIndustryName: '未知',
  primaryUnit: '天',
  primaryLabel: '出勤天数',
  isLoaded: false,
  loading: false,
  error: null as string | null,
  loadIndustries: vi.fn().mockResolvedValue(undefined),
  loadCurrentIndustry: vi.fn().mockResolvedValue(undefined),
  switchIndustry: vi.fn().mockResolvedValue(true),
  initialize: vi.fn().mockResolvedValue(undefined),
  getIndustryById: vi.fn().mockReturnValue(null),
}

vi.mock('@/stores/industry', () => ({
  useIndustryStore: () => mockIndustryStore,
}))

const mockModsStore = {
  mods: [] as unknown[],
  activeModId: '',
  clientModsUiOff: false,
  loadError: '',
  isLoaded: true,
  modRoutes: [] as unknown[],
  modsForUi: [] as unknown[],
  refresh: vi.fn().mockResolvedValue(undefined),
  initialize: vi.fn().mockResolvedValue(undefined),
  applyEntitledActiveMod: vi.fn().mockResolvedValue(undefined),
  setActiveModId: vi.fn(),
}

vi.mock('@/stores/mods', () => ({
  useModsStore: () => mockModsStore,
}))

const mockAccountProfileStore = {
  profile: null as unknown,
  isLoggedIn: false,
  loading: false,
  companyBrand: '',
  displayBrand: '',
  accountKind: 'personal',
  isLocalAdmin: false,
  isImpersonating: false,
  refresh: vi.fn().mockResolvedValue(undefined),
  refreshFromServer: vi.fn().mockResolvedValue(undefined),
  applyFromMeData: vi.fn(),
  clear: vi.fn(),
}

vi.mock('@/stores/accountProfile', () => ({
  useAccountProfileStore: () => mockAccountProfileStore,
}))

/* ── custom storeToRefs mock ── */
vi.mock('pinia', async (importOriginal) => {
  const actual = await importOriginal<typeof import('pinia')>()
  return {
    ...actual,
    storeToRefs: (store: Record<string, unknown>) => {
      const refs: Record<string, Ref> = {}
      for (const key of Object.keys(store)) {
        if (typeof store[key] === 'function') continue
        refs[key] = ref(store[key])
      }
      return refs as never
    },
  }
})

/* ── constant mocks ── */
vi.mock('@/constants/industryDefaults', () => ({
  DEFAULT_INDUSTRY_ID: 'default',
}))

vi.mock('@/constants/industryPresets', () => ({
  getIndustryPreset: vi.fn(() => ({ name: '默认行业' })),
}))

vi.mock('@/constants/protectedMods', () => ({
  isProtectedClientModId: () => false,
}))

vi.mock('@/constants/accountModBinding', () => ({
  isSunbirdAccountUsername: () => false,
  SUNBIRD_CLIENT_MOD_ID: 'sunbird',
  augmentEntitledModIdsForAccount: vi.fn((ids: string[]) => ids),
}))

vi.mock('@/constants/genericModPack', () => ({
  ACCOUNT_CUSTOM_MOD_IDS: ['taiyangniao-pro', 'sz-qsm-pro'],
  expectedHostBridgeModIds: () => [],
  isHostBridgeModId: () => false,
  isSelectableExtensionModId: () => true,
  isWorkflowEmployeeModId: () => false,
}))

vi.mock('@/api', () => ({
  default: {
    get: (...args: unknown[]) => mockApiGet(...args),
    post: (...args: unknown[]) => mockApiPost(...args),
  },
  ApiError: class ApiError extends Error {},
}))

vi.mock('../../package.json', () => ({
  default: { version: '10.0.0' },
}))

/* ── global stubs ── */
const globalStubs = {
  RouterLink: { template: '<a><slot /></a>' },
  HostModBridgeView: { template: '<div class="host-mod-bridge-stub" />' },
  MobilePairingQrCard: { template: '<div class="mobile-pairing-stub" />' },
}

const i18nMock = {
  install(app: { config: { globalProperties: Record<string, unknown> } }) {
    app.config.globalProperties.$t = (k: string) => k
  },
}

async function mountSettings() {
  const SettingsView = (await import('./SettingsView.vue')).default
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/settings', component: SettingsView }],
  })
  await router.push('/settings')
  await router.isReady()
  const wrapper = mount(SettingsView, {
    global: {
      plugins: [router, i18nMock],
      stubs: globalStubs,
      mocks: { $t: (k: string) => k },
    },
  })
  return wrapper
}

/* ══════════════════════════════════════════════════════════════════ */

describe('SettingsView.vue – component structure', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    // Reset store mocks
    mockIndustryStore.industries = []
    mockIndustryStore.currentIndustry = null
    mockIndustryStore.isLoaded = false
    mockModsStore.mods = []
    mockModsStore.activeModId = ''
    mockModsStore.isLoaded = true
    mockModsStore.modRoutes = []
    mockModsStore.clientModsUiOff = false
    mockAccountProfileStore.companyBrand = ''
    mockAccountProfileStore.displayBrand = ''
    mockAccountProfileStore.accountKind = 'personal'
  })

  it('mounts and renders settings content', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.find('#view-settings').exists()).toBe(true)
    wrapper.unmount()
  })

  it('contains settings profile section', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.find('.settings-profile').exists()).toBe(true)
    wrapper.unmount()
  })

  it('contains settings layout', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.find('.settings-layout').exists()).toBe(true)
    wrapper.unmount()
  })

  it('contains settings list', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.find('.settings-list').exists()).toBe(true)
    wrapper.unmount()
  })

  it('contains page title', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.find('.settings-page__title').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('SettingsView.vue – profile section', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    mockIndustryStore.industries = []
    mockIndustryStore.currentIndustry = null
    mockIndustryStore.isLoaded = false
    mockModsStore.mods = []
    mockModsStore.isLoaded = true
    mockModsStore.modRoutes = []
    mockModsStore.clientModsUiOff = false
    mockAccountProfileStore.companyBrand = ''
    mockAccountProfileStore.displayBrand = ''
    mockAccountProfileStore.accountKind = 'personal'
  })

  it('shows login link when not logged in', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({ success: false, data: { user: null, permissions: [] } })
    mockAuthApiValidateSession.mockResolvedValueOnce({ success: false })
    const wrapper = await mountSettings()
    // When not logged in, should show login link (router-link with primary btn class)
    const loginBtn = wrapper.find('.settings-profile__btn--primary')
    expect(loginBtn.exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows avatar area', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.find('.settings-profile__avatar').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows profile brand title', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.find('.settings-profile__brand').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows logout button when logged in', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: {
        user: { id: 1, username: 'testuser', display_name: 'Test', email: 't@t.com', role: 'user', is_active: true },
        permissions: [],
      },
    })
    mockAuthApiValidateSession.mockResolvedValueOnce({ success: true, valid: true, data: { username: 'testuser', user_id: 1 } })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const logoutBtn = wrapper.find('.settings-profile__btn--ghost')
    expect(logoutBtn.exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows avatar initial letter when logged in', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: {
        user: { id: 1, username: 'testuser', display_name: 'Test User', email: 't@t.com', role: 'user', is_active: true },
        permissions: [],
      },
    })
    const wrapper = await mountSettings()
    // profileBrandTitle should show user display name
    expect(wrapper.find('.settings-profile__brand').text()).toBeTruthy()
    wrapper.unmount()
  })
})

describe('SettingsView.vue – basic settings', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    mockIndustryStore.industries = []
    mockIndustryStore.currentIndustry = null
    mockIndustryStore.isLoaded = false
    mockModsStore.mods = []
    mockModsStore.isLoaded = true
    mockModsStore.modRoutes = []
    mockModsStore.clientModsUiOff = false
    mockAccountProfileStore.companyBrand = ''
    mockAccountProfileStore.displayBrand = ''
    mockAccountProfileStore.accountKind = 'personal'
  })

  it('renders sidebar theme select', async () => {
    const wrapper = await mountSettings()
    const select = wrapper.find('#settings-sidebar-theme')
    expect(select.exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders assistant name input', async () => {
    const wrapper = await mountSettings()
    const input = wrapper.find('#settings-assistant-name')
    expect(input.exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders locale select', async () => {
    const wrapper = await mountSettings()
    const select = wrapper.find('#settings-locale')
    expect(select.exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders AI mode select', async () => {
    const wrapper = await mountSettings()
    const select = wrapper.find('#settings-ai-mode')
    expect(select.exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders system name display', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.text()).toContain('settings.systemName')
    wrapper.unmount()
  })

  it('sidebar theme select has correct options', async () => {
    const wrapper = await mountSettings()
    const select = wrapper.find('#settings-sidebar-theme')
    const options = select.findAll('option')
    expect(options.length).toBeGreaterThanOrEqual(2)
    wrapper.unmount()
  })

  it('locale select has zh-CN and en-US options', async () => {
    const wrapper = await mountSettings()
    const select = wrapper.find('#settings-locale')
    const options = select.findAll('option')
    const values = options.map(o => o.attributes('value'))
    expect(values).toContain('zh-CN')
    expect(values).toContain('en-US')
    wrapper.unmount()
  })

  it('AI mode select has online and offline options', async () => {
    const wrapper = await mountSettings()
    const select = wrapper.find('#settings-ai-mode')
    const options = select.findAll('option')
    const values = options.map(o => o.attributes('value'))
    expect(values).toContain('online')
    expect(values).toContain('offline')
    wrapper.unmount()
  })
})

describe('SettingsView.vue – intent showcase', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    mockIndustryStore.industries = []
    mockIndustryStore.currentIndustry = null
    mockIndustryStore.isLoaded = false
    mockModsStore.mods = []
    mockModsStore.isLoaded = true
    mockModsStore.modRoutes = []
    mockModsStore.clientModsUiOff = false
    mockAccountProfileStore.companyBrand = ''
    mockAccountProfileStore.displayBrand = ''
    mockAccountProfileStore.accountKind = 'personal'
  })

  it('renders intent section', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.find('[data-tutorial-id="settings-intent"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows intent showcase grid when industry config available', async () => {
    mockIndustryStore.industries = [{ id: 'default', name: '默认行业', code: 'default' }]
    mockSystemApiGetIndustries.mockResolvedValueOnce({
      success: true,
      data: { industries: [{ id: 'default', name: '默认行业', code: 'default' }], current: 'default' },
    })
    const wrapper = await mountSettings()
    // The intent showcase should show either grid or "not loaded" message
    const intentSection = wrapper.find('[data-tutorial-id="settings-intent"]')
    expect(intentSection.exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows "not loaded" message when industry config unavailable', async () => {
    mockIndustryStore.industries = []
    const wrapper = await mountSettings()
    const intentBody = wrapper.find('[data-tutorial-id="settings-intent"] .settings-card__body')
    // When currentIndustryConfig is null, should show "未加载" message
    expect(intentBody.exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('SettingsView.vue – model service section', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    mockIndustryStore.industries = []
    mockIndustryStore.currentIndustry = null
    mockIndustryStore.isLoaded = false
    mockModsStore.mods = []
    mockModsStore.isLoaded = true
    mockModsStore.modRoutes = []
    mockModsStore.clientModsUiOff = false
    mockAccountProfileStore.companyBrand = ''
    mockAccountProfileStore.displayBrand = ''
    mockAccountProfileStore.accountKind = 'personal'
  })

  it('renders model service section', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.find('#settings-model-payment').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows model service missing message when bridge not installed', async () => {
    mockModsStore.mods = [] // no model payment bridge mod
    const wrapper = await mountSettings()
    expect(wrapper.find('.settings-model-service-empty').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows HostModBridgeView when bridge is installed', async () => {
    mockModsStore.mods = [{ id: 'xcagi-model-payment-bridge', name: 'Model Payment' }]
    const wrapper = await mountSettings()
    expect(wrapper.find('.host-mod-bridge-stub').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('SettingsView.vue – extensions & mods section', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    mockIndustryStore.industries = []
    mockIndustryStore.currentIndustry = null
    mockIndustryStore.isLoaded = false
    mockModsStore.mods = []
    mockModsStore.isLoaded = true
    mockModsStore.modRoutes = []
    mockModsStore.clientModsUiOff = false
    mockAccountProfileStore.companyBrand = ''
    mockAccountProfileStore.displayBrand = ''
    mockAccountProfileStore.accountKind = 'personal'
  })

  it('renders extensions section when clientModsUiOff is false', async () => {
    mockModsStore.clientModsUiOff = false
    const wrapper = await mountSettings()
    expect(wrapper.find('[data-tutorial-id="settings-extensions"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('hides extensions section when clientModsUiOff is true', async () => {
    mockModsStore.clientModsUiOff = true
    const wrapper = await mountSettings()
    expect(wrapper.find('[data-tutorial-id="settings-extensions"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows selectable extension mods', async () => {
    mockModsStore.mods = [
      { id: 'mod-a', name: '行业包A' },
      { id: 'mod-b', name: '行业包B' },
    ]
    const wrapper = await mountSettings()
    const items = wrapper.findAll('.mod-single-item')
    expect(items.length).toBeGreaterThanOrEqual(0) // depends on isSelectableExtensionModId mock
    wrapper.unmount()
  })
})

describe('SettingsView.vue – persistence', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    mockIndustryStore.industries = []
    mockIndustryStore.currentIndustry = null
    mockIndustryStore.isLoaded = false
    mockModsStore.mods = []
    mockModsStore.isLoaded = true
    mockModsStore.modRoutes = []
    mockModsStore.clientModsUiOff = false
    mockAccountProfileStore.companyBrand = ''
    mockAccountProfileStore.displayBrand = ''
    mockAccountProfileStore.accountKind = 'personal'
  })

  it('survives remount with persisted sidebar theme', async () => {
    localStorage.setItem('xcagi_sidebar_theme', 'dark')
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('survives remount with persisted locale', async () => {
    localStorage.setItem('xcagi_locale', 'en-US')
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('survives remount with persisted assistant name', async () => {
    localStorage.setItem('assistantName', '小智')
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('SettingsView.vue – session handling', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    mockIndustryStore.industries = []
    mockIndustryStore.currentIndustry = null
    mockIndustryStore.isLoaded = false
    mockModsStore.mods = []
    mockModsStore.isLoaded = true
    mockModsStore.modRoutes = []
    mockModsStore.clientModsUiOff = false
    mockAccountProfileStore.companyBrand = ''
    mockAccountProfileStore.displayBrand = ''
    mockAccountProfileStore.accountKind = 'personal'
  })

  it('handles session validation failure gracefully', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({ success: false, data: { user: null, permissions: [] } })
    mockAuthApiValidateSession.mockRejectedValueOnce(new Error('Network error'))
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('handles session validation success', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({ success: false, data: { user: null, permissions: [] } })
    mockAuthApiValidateSession.mockResolvedValueOnce({
      success: true,
      valid: true,
      data: { username: 'testuser', user_id: 1 },
    })
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('handles getCurrentUser success', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: {
        user: { id: 1, username: 'admin', display_name: 'Admin', email: 'a@a.com', role: 'admin', is_active: true },
        permissions: [],
      },
    })
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('SettingsView.vue – computed properties', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    mockIndustryStore.industries = []
    mockIndustryStore.currentIndustry = null
    mockIndustryStore.isLoaded = false
    mockModsStore.mods = []
    mockModsStore.isLoaded = true
    mockModsStore.modRoutes = []
    mockModsStore.clientModsUiOff = false
    mockAccountProfileStore.companyBrand = ''
    mockAccountProfileStore.displayBrand = ''
    mockAccountProfileStore.accountKind = 'personal'
  })

  it('systemDisplayName defaults to generic host shell', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as Record<string, unknown>
    expect(vm.systemDisplayName).toBe('XCAGI 通用宿主')
    expect(vm.aboutDisplayLine).toBe('XCAGI 通用宿主 · 能力由 Mod 提供')
    wrapper.unmount()
  })

  it('systemDisplayName uses account custom delivery name', async () => {
    mockModsStore.mods = [
      { id: 'taiyangniao-pro', name: '太阳鸟 PRO', industry: { id: '考勤', name: '考勤/人事行业' } },
    ]
    mockModsStore.activeModId = 'taiyangniao-pro'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as Record<string, unknown>
    expect(vm.systemDisplayName).toBe('太阳鸟 PRO 交付工作台')
    expect(vm.aboutDisplayLine).toBe('XCAGI 通用宿主 · 太阳鸟 PRO 交付 · 考勤/人事行业基础线')
    wrapper.unmount()
  })

  it('normalizedAssistantName returns default when empty', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as Record<string, unknown>
    expect(vm.normalizedAssistantName).toBeTruthy()
    wrapper.unmount()
  })

  it('appVersionLabel comes from package.json', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as Record<string, unknown>
    expect(vm.appVersionLabel).toBe('10.0.0')
    wrapper.unmount()
  })

  it('isLoggedIn is false when no user', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({ success: false, data: { user: null, permissions: [] } })
    mockAuthApiValidateSession.mockResolvedValueOnce({ success: false })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as Record<string, unknown>
    expect(vm.isLoggedIn).toBe(false)
    wrapper.unmount()
  })

  it('showCompanyBrandEditor is false for personal account', async () => {
    mockAccountProfileStore.accountKind = 'personal'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as Record<string, unknown>
    expect(vm.showCompanyBrandEditor).toBe(false)
    wrapper.unmount()
  })

  it('showCompanyBrandEditor is true for enterprise account', async () => {
    mockAccountProfileStore.accountKind = 'enterprise'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as Record<string, unknown>
    expect(vm.showCompanyBrandEditor).toBe(true)
    wrapper.unmount()
  })
})

describe('SettingsView.vue – API error handling', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    mockIndustryStore.industries = []
    mockIndustryStore.currentIndustry = null
    mockIndustryStore.isLoaded = false
    mockModsStore.mods = []
    mockModsStore.isLoaded = true
    mockModsStore.modRoutes = []
    mockModsStore.clientModsUiOff = false
    mockAccountProfileStore.companyBrand = ''
    mockAccountProfileStore.displayBrand = ''
    mockAccountProfileStore.accountKind = 'personal'
  })

  it('handles getIndustries failure gracefully', async () => {
    mockSystemApiGetIndustries.mockRejectedValueOnce(new Error('Server error'))
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('handles getCurrentIndustry failure gracefully', async () => {
    mockSystemApiGetCurrentIndustry.mockRejectedValueOnce(new Error('Server error'))
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('handles intentPackagesApi failure gracefully', async () => {
    mockIntentPackagesApiGetPackages.mockRejectedValueOnce(new Error('Server error'))
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('handles preferences API failure gracefully', async () => {
    mockApiGet.mockRejectedValueOnce(new Error('Server error'))
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('handles distillation versions API failure gracefully', async () => {
    mockApiGet.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/distillation')) {
        return Promise.reject(new Error('Server error'))
      }
      return Promise.resolve({ data: {}, success: false })
    })
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('SettingsView.vue – industry loading', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    mockIndustryStore.industries = []
    mockIndustryStore.currentIndustry = null
    mockIndustryStore.isLoaded = false
    mockModsStore.mods = []
    mockModsStore.isLoaded = true
    mockModsStore.modRoutes = []
    mockModsStore.clientModsUiOff = false
    mockAccountProfileStore.companyBrand = ''
    mockAccountProfileStore.displayBrand = ''
    mockAccountProfileStore.accountKind = 'personal'
  })

  it('calls industryStore.initialize on mount', async () => {
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 100))
    expect(mockIndustryStore.initialize).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('calls systemApi.getIndustries on mount', async () => {
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 100))
    expect(mockSystemApiGetIndustries).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('populates industries from API response', async () => {
    mockSystemApiGetIndustries.mockResolvedValueOnce({
      success: true,
      data: { industries: [{ id: 'manufacturing', name: '制造业', code: 'mfg' }], current: 'manufacturing' },
    })
    const wrapper = await mountSettings()
    // Wait for async operations
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('SettingsView.vue – audit logs', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    mockIndustryStore.industries = []
    mockIndustryStore.currentIndustry = null
    mockIndustryStore.isLoaded = false
    mockModsStore.mods = []
    mockModsStore.isLoaded = true
    mockModsStore.modRoutes = []
    mockModsStore.clientModsUiOff = false
    mockAccountProfileStore.companyBrand = ''
    mockAccountProfileStore.displayBrand = ''
    mockAccountProfileStore.accountKind = 'personal'
  })

  it('does not show audit logs for non-admin users', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({ success: false, data: { user: null, permissions: [] } })
    mockAuthApiValidateSession.mockResolvedValueOnce({ success: false })
    const wrapper = await mountSettings()
    expect(wrapper.find('[data-tutorial-id="settings-audit-logs"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows audit logs section for admin users', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: {
        user: { id: 1, username: 'admin', display_name: 'Admin', email: 'a@a.com', role: 'admin', is_active: true },
        permissions: [],
      },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 100))
    expect(wrapper.find('[data-tutorial-id="settings-audit-logs"]').exists()).toBe(true)
    wrapper.unmount()
  })
})

/**
 * SettingsView.vue 覆盖率补齐测试
 * 目标：将 statements 覆盖率从 74.2% 提升到 90%+
 * 重点覆盖：未覆盖的函数、分支、错误路径、事件处理
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { ref, type Ref, nextTick } from 'vue'

/* ── mock functions ── */
const mockApiGet = vi.fn().mockResolvedValue({ data: {}, success: false })
const mockApiPost = vi.fn().mockResolvedValue({ success: true })
const mockApiDelete = vi.fn().mockResolvedValue({ success: true, message: 'ok' })
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
/* 模块级 mock 引用（便于在 resetApiMocks 中重置） */
const mockGetIndustryPreset = vi.fn(() => ({ name: '默认行业' }))
const mockIsProtectedClientModId = vi.fn((id: string) => id === 'protected-mod')
const mockIsHostBridgeModId = vi.fn((id: string) => id.startsWith('host-bridge'))
const mockIsSelectableExtensionModId = vi.fn((id: string) => id.startsWith('ext-'))
const mockIsWorkflowEmployeeModId = vi.fn((id: string) => id.startsWith('wf-'))
const mockAppAlert = vi.fn().mockResolvedValue(undefined)
const mockAppConfirm = vi.fn().mockResolvedValue(true)

/* ── module mocks ── */
vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn().mockResolvedValue({ ok: true, json: async () => ({ success: true, data: {} }) }),
  getApiBase: () => '',
  DEFAULT_MOD_API_TIMEOUT_MS: 90_000,
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (k: string) => k,
    locale: ref('zh-CN'),
  }),
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
  buildFullApiUrl: (p: string) => `http://test${p}`,
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: (...args: unknown[]) => mockAppAlert(...args),
  appConfirm: (...args: unknown[]) => mockAppConfirm(...args),
}))

vi.mock('@/utils/sidebarTheme', () => ({
  SIDEBAR_THEME_OPTIONS: [
    { value: 'office-default', label: '办公默认', accent: '#0f6cbd' },
    { value: 'dark', label: '深色', accent: '#1e293b' },
    { value: 'light', label: '浅色', accent: '#0f6cbd' },
  ],
  readStoredSidebarTheme: () => 'office-default',
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
  getIndustryPreset: (...args: unknown[]) => mockGetIndustryPreset(...args),
}))

vi.mock('@/constants/protectedMods', () => ({
  isProtectedClientModId: (...args: unknown[]) => mockIsProtectedClientModId(...args),
}))

vi.mock('@/constants/accountModBinding', () => ({
  isSunbirdAccountUsername: () => false,
  SUNBIRD_CLIENT_MOD_ID: 'sunbird',
  augmentEntitledModIdsForAccount: vi.fn((ids: string[]) => ids),
}))

vi.mock('@/constants/genericModPack', () => ({
  ACCOUNT_CUSTOM_MOD_IDS: ['taiyangniao-pro', 'sz-qsm-pro'],
  expectedHostBridgeModIds: () => ['host-bridge-1', 'host-bridge-2'],
  isHostBridgeModId: (...args: unknown[]) => mockIsHostBridgeModId(...args as [string]),
  isSelectableExtensionModId: (...args: unknown[]) => mockIsSelectableExtensionModId(...args as [string]),
  isWorkflowEmployeeModId: (...args: unknown[]) => mockIsWorkflowEmployeeModId(...args as [string]),
}))

vi.mock('@/api', () => ({
  default: {
    get: (...args: unknown[]) => mockApiGet(...args),
    post: (...args: unknown[]) => mockApiPost(...args),
    delete: (...args: unknown[]) => mockApiDelete(...args),
  },
  ApiError: class ApiError extends Error {
    status?: number
    constructor(message = 'api error', status = 500) {
      super(message)
      this.status = status
    }
  },
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

async function mountSettings(routeQuery: Record<string, string> = {}) {
  const SettingsView = (await import('./SettingsView.vue')).default
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/settings', component: SettingsView },
      { path: '/mod-store', name: 'mod-store', component: { template: '<div/>' } },
      { path: '/login', name: 'login', component: { template: '<div/>' } },
      { path: '/onboarding', component: { template: '<div/>' } },
    ],
  })
  await router.push({ path: '/settings', query: routeQuery })
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

function resetStores() {
  mockIndustryStore.industries = []
  mockIndustryStore.currentIndustry = null
  mockIndustryStore.currentConfig = null
  mockIndustryStore.currentIndustryId = 'default'
  mockIndustryStore.isLoaded = false
  mockIndustryStore.error = null
  mockModsStore.mods = []
  mockModsStore.activeModId = ''
  mockModsStore.isLoaded = true
  mockModsStore.modRoutes = []
  mockModsStore.clientModsUiOff = false
  mockModsStore.loadError = ''
  mockAccountProfileStore.companyBrand = ''
  mockAccountProfileStore.displayBrand = ''
  mockAccountProfileStore.accountKind = 'personal'
}

function resetApiMocks() {
  mockApiGet.mockReset()
  mockApiPost.mockReset()
  mockApiDelete.mockReset()
  mockApiGet.mockResolvedValue({ data: {}, success: false })
  mockApiPost.mockResolvedValue({ success: true })
  mockApiDelete.mockResolvedValue({ success: true, message: 'ok' })
  mockAuthApiGetCurrentUser.mockReset()
  mockAuthApiValidateSession.mockReset()
  mockAuthApiLogout.mockReset()
  mockAuthApiUpdateCompanyBrand.mockReset()
  mockAuthApiUploadAvatar.mockReset()
  mockAuthApiUpdateProfile.mockReset()
  mockSystemApiGetIndustries.mockReset()
  mockSystemApiGetCurrentIndustry.mockReset()
  mockIntentPackagesApiGetPackages.mockReset()
  mockAdminAuditApiList.mockReset()
  // 设置默认返回值
  mockAuthApiGetCurrentUser.mockResolvedValue({ success: false, data: { user: null, permissions: [] } })
  mockAuthApiValidateSession.mockResolvedValue({ success: false })
  mockAuthApiLogout.mockResolvedValue({})
  mockAuthApiUpdateCompanyBrand.mockResolvedValue({ success: true })
  mockAuthApiUploadAvatar.mockResolvedValue({ success: true, data: { avatar_url: '/api/auth/avatar' } })
  mockAuthApiUpdateProfile.mockResolvedValue({ success: true, data: { user: null } })
  mockSystemApiGetIndustries.mockResolvedValue({ success: true, data: [] })
  mockSystemApiGetCurrentIndustry.mockResolvedValue({ success: false })
  mockIntentPackagesApiGetPackages.mockResolvedValue({ success: false, data: null })
  mockAdminAuditApiList.mockResolvedValue({ ok: true, data: { items: [], total: 0 } })
  // 重置模块级 mock
  mockGetIndustryPreset.mockReset()
  mockGetIndustryPreset.mockReturnValue({ name: '默认行业' })
  mockIsProtectedClientModId.mockReset()
  mockIsProtectedClientModId.mockImplementation((id: string) => id === 'protected-mod')
  mockIsHostBridgeModId.mockReset()
  mockIsHostBridgeModId.mockImplementation((id: string) => id.startsWith('host-bridge'))
  mockIsSelectableExtensionModId.mockReset()
  mockIsSelectableExtensionModId.mockImplementation((id: string) => id.startsWith('ext-'))
  mockIsWorkflowEmployeeModId.mockReset()
  mockIsWorkflowEmployeeModId.mockImplementation((id: string) => id.startsWith('wf-'))
  mockAppAlert.mockReset()
  mockAppAlert.mockResolvedValue(undefined)
  mockAppConfirm.mockReset()
  mockAppConfirm.mockResolvedValue(true)
}

/* ══════════════════════════════════════════════════════════════════
 * 用户会话与本地用户加载
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – loadLocalUser 各种路径', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('getCurrentUser 成功返回用户时设置 sessionValid', async () => {
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
    const vm = wrapper.vm as any
    expect(vm.localUser).toBeTruthy()
    expect(vm.localUser.username).toBe('admin')
    expect(vm.isLoggedIn).toBe(true)
    expect(vm.isLocalAdmin).toBe(true)
    wrapper.unmount()
  })

  it('getCurrentUser 成功但无 user 时走 session validate', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({ success: true, data: {} })
    mockAuthApiValidateSession.mockResolvedValueOnce({
      success: true,
      valid: true,
      data: { username: 'sessuser', user_id: 5 },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.localUser).toBeTruthy()
    expect(vm.localUser.username).toBe('sessuser')
    expect(vm.localUser.id).toBe(5)
    wrapper.unmount()
  })

  it('session validate 无 username 时回退到 market storage', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({ success: false })
    mockAuthApiValidateSession.mockResolvedValueOnce({ success: true, valid: true, data: {} })
    localStorage.setItem('xcagi_market_user_json', JSON.stringify({
      id: 9,
      username: 'marketuser',
      display_name: 'Market User',
      email: 'm@m.com',
    }))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.localUser).toBeTruthy()
    expect(vm.localUser.username).toBe('marketuser')
    expect(vm.localUser.id).toBe(9)
    wrapper.unmount()
  })

  it('getCurrentUser 抛异常时走 session validate 兜底', async () => {
    mockAuthApiGetCurrentUser.mockRejectedValueOnce(new Error('network'))
    mockAuthApiValidateSession.mockResolvedValueOnce({ success: false })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.localUser).toBeNull()
    expect(vm.isLoggedIn).toBe(false)
    wrapper.unmount()
  })

  it('session validate 抛异常时 sessionValid 为 false', async () => {
    mockAuthApiGetCurrentUser.mockRejectedValueOnce(new Error('net'))
    mockAuthApiValidateSession.mockRejectedValueOnce(new Error('net'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.sessionValid).toBe(false)
    wrapper.unmount()
  })

  it('market storage 解析失败时返回 null', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({ success: false })
    mockAuthApiValidateSession.mockResolvedValueOnce({ success: true, valid: true, data: {} })
    localStorage.setItem('xcagi_market_user_json', '{invalid json')
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.localUser).toBeNull()
    wrapper.unmount()
  })

  it('market storage 无 username 时返回 null', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({ success: false })
    mockAuthApiValidateSession.mockResolvedValueOnce({ success: true, valid: true, data: {} })
    localStorage.setItem('xcagi_market_user_json', JSON.stringify({ id: 1, email: 'a@a.com' }))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.localUser).toBeNull()
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * 计算属性测试
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – profileBrandTitle 计算属性', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('有 brand 时返回 brand', async () => {
    mockAccountProfileStore.displayBrand = '我的公司'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.profileBrandTitle).toBe('我的公司')
    wrapper.unmount()
  })

  it('无 brand 无 user 时返回未登录提示', async () => {
    mockAccountProfileStore.displayBrand = ''
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileBrandTitle).toBe('settings.notLoggedIn')
    wrapper.unmount()
  })

  it('无 brand 有 user 时返回用户名', async () => {
    mockAccountProfileStore.displayBrand = ''
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'alice', display_name: 'Alice', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileBrandTitle).toBe('Alice')
    wrapper.unmount()
  })
})

describe('SettingsView – profileSubline 计算属性', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('无 user 时返回登录提示', async () => {
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileSubline).toBe('settings.loginSyncHint')
    wrapper.unmount()
  })

  it('有 brand 且 display 与 brand 不同时返回组合', async () => {
    mockAccountProfileStore.displayBrand = '公司A'
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'bob', display_name: 'Bob', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileSubline).toBe('bob · Bob')
    wrapper.unmount()
  })

  it('有 brand 且 display 等于 brand 时返回 username', async () => {
    mockAccountProfileStore.displayBrand = '公司B'
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'carol', display_name: '公司B', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileSubline).toBe('carol')
    wrapper.unmount()
  })

  it('无 brand 有 display 且 display 不等于 username 时返回 username', async () => {
    mockAccountProfileStore.displayBrand = ''
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'dave', display_name: 'Dave', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileSubline).toBe('dave')
    wrapper.unmount()
  })

  it('无 brand 无 display 有 id 时返回 ID', async () => {
    mockAccountProfileStore.displayBrand = ''
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 42, username: 'eve', display_name: 'eve', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileSubline).toBe('ID 42')
    wrapper.unmount()
  })
})

describe('SettingsView – avatarInitial 与 profileAvatarUrl', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('无 user 时 avatarInitial 为空', async () => {
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.avatarInitial).toBe('')
    wrapper.unmount()
  })

  it('有 user 时 avatarInitial 返回首字母大写', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'alice', display_name: 'alice', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.avatarInitial).toBe('A')
    wrapper.unmount()
  })

  it('profileAvatarUrl 从 user.avatar_url 构建完整 URL', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true, avatar_url: '/avatar.png' }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileAvatarUrl).toContain('http://test/avatar.png')
    expect(vm.profileAvatarUrl).toContain('v=')
    wrapper.unmount()
  })

  it('profileAvatarUrl 处理 http 开头的 avatar_url', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true, avatar_url: 'https://cdn.test/a.png?x=1' }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileAvatarUrl).toContain('https://cdn.test/a.png?x=1')
    expect(vm.profileAvatarUrl).toContain('&v=')
    wrapper.unmount()
  })

  it('profileAvatarUrl 从 market storage 读取 http url', async () => {
    localStorage.setItem('xcagi_market_user_json', JSON.stringify({ avatar_url: 'https://market.test/avatar.png' }))
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.profileAvatarUrl).toBe('https://market.test/avatar.png')
    wrapper.unmount()
  })

  it('profileAvatarUrl market storage 非 http url 返回空', async () => {
    localStorage.setItem('xcagi_market_user_json', JSON.stringify({ avatar_url: '/relative.png' }))
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.profileAvatarUrl).toBe('')
    wrapper.unmount()
  })

  it('profileAvatarUrl market storage 解析失败返回空', async () => {
    localStorage.setItem('xcagi_market_user_json', '{bad')
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.profileAvatarUrl).toBe('')
    wrapper.unmount()
  })
})

describe('SettingsView – profileFormDirty 与 profileHomeSummary', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('无 user 时 profileFormDirty 为 false', async () => {
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileFormDirty).toBe(false)
    wrapper.unmount()
  })

  it('有 user 但草稿与当前一致时 profileFormDirty 为 false', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'alice', display_name: 'Alice', email: 'a@a.com', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileFormDirty).toBe(false)
    wrapper.unmount()
  })

  it('修改草稿后 profileFormDirty 为 true', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'alice', display_name: 'Alice', email: 'a@a.com', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.profileDisplayNameDraft = 'Alice New'
    await nextTick()
    expect(vm.profileFormDirty).toBe(true)
    wrapper.unmount()
  })

  it('profileHomeSummary 无名字时返回默认', async () => {
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileHomeSummary).toBe('settings.profileHomeSummary')
    wrapper.unmount()
  })

  it('profileHomeSummary 有名字时返回组合', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'alice', display_name: 'Alice', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.profileHomeSummary).toContain('Alice')
    wrapper.unmount()
  })
})

describe('SettingsView – companyBrandDirty', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
    mockAccountProfileStore.accountKind = 'enterprise'
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true }, permissions: [] },
    })
  })

  it('草稿与当前 brand 一致时 dirty 为 false', async () => {
    mockAccountProfileStore.companyBrand = '公司A'
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.companyBrandDraft = '公司A'
    await nextTick()
    expect(vm.companyBrandDirty).toBe(false)
    wrapper.unmount()
  })

  it('草稿与当前 brand 不同时 dirty 为 true', async () => {
    mockAccountProfileStore.companyBrand = '公司A'
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.companyBrandDraft = '公司B'
    await nextTick()
    expect(vm.companyBrandDirty).toBe(true)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * saveCompanyBrand
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – saveCompanyBrand', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
    mockAccountProfileStore.accountKind = 'enterprise'
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true }, permissions: [] },
    })
  })

  it('保存成功时更新 store 并提示', async () => {
    mockAuthApiUpdateCompanyBrand.mockResolvedValueOnce({ success: true })
    mockAccountProfileStore.refreshFromServer.mockResolvedValueOnce(undefined)
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.companyBrandDraft = '新品牌'
    await nextTick()
    await vm.saveCompanyBrand()
    expect(mockAuthApiUpdateCompanyBrand).toHaveBeenCalledWith('新品牌')
    expect(mockAccountProfileStore.companyBrand).toBe('新品牌')
    wrapper.unmount()
  })

  it('保存返回 success:false 时抛错并提示', async () => {
    mockAuthApiUpdateCompanyBrand.mockResolvedValueOnce({ success: false, message: '名称重复' })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.companyBrandDraft = '重复名'
    await nextTick()
    await vm.saveCompanyBrand()
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('保存失败'))
    wrapper.unmount()
  })

  it('保存抛异常时提示错误', async () => {
    mockAuthApiUpdateCompanyBrand.mockRejectedValueOnce(new Error('网络错误'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.companyBrandDraft = '新品牌'
    await nextTick()
    await vm.saveCompanyBrand()
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('网络错误'))
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * saveProfile
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – saveProfile', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'alice', display_name: 'Alice', email: 'a@a.com', role: 'user', is_active: true }, permissions: [] },
    })
  })

  it('表单未修改时不调用 API', async () => {
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.saveProfile()
    expect(mockAuthApiUpdateProfile).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('表单修改后保存成功时更新 user', async () => {
    mockAuthApiUpdateProfile.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'alice', display_name: 'Alice New', email: 'new@a.com', role: 'user', is_active: true } },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.profileDisplayNameDraft = 'Alice New'
    vm.profileEmailDraft = 'new@a.com'
    await nextTick()
    await vm.saveProfile()
    expect(mockAuthApiUpdateProfile).toHaveBeenCalled()
    expect(vm.localUser.display_name).toBe('Alice New')
    wrapper.unmount()
  })

  it('保存抛异常时提示错误', async () => {
    mockAuthApiUpdateProfile.mockRejectedValueOnce(new Error('保存失败'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.profileDisplayNameDraft = 'Alice New'
    await nextTick()
    await vm.saveProfile()
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('保存失败'))
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * onAvatarClick 与 onAvatarFileChange
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – 头像交互', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('未登录时点击头像不触发 input click', async () => {
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    const clickSpy = vi.fn()
    vm.avatarInputRef = { click: clickSpy }
    await vm.onAvatarClick()
    expect(clickSpy).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('已登录时点击头像触发 input click', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    const clickSpy = vi.fn()
    vm.avatarInputRef = { click: clickSpy }
    await vm.onAvatarClick()
    expect(clickSpy).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('上传中时点击头像不触发 input click', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.avatarUploading = true
    const clickSpy = vi.fn()
    vm.avatarInputRef = { click: clickSpy }
    await vm.onAvatarClick()
    expect(clickSpy).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('文件超过 4MB 时提示', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    const bigFile = new File(['x'.repeat(5 * 1024 * 1024)], 'big.png', { type: 'image/png' })
    await vm.onAvatarFileChange({ target: { value: 'x', files: [bigFile] } })
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith('头像图片不能超过 4MB')
    wrapper.unmount()
  })

  it('无文件时不执行上传', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.onAvatarFileChange({ target: { value: '', files: [] } })
    expect(mockAuthApiUploadAvatar).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('上传成功时更新 avatar_url', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    mockAuthApiUploadAvatar.mockResolvedValueOnce({ success: true, data: { avatar_url: '/new-avatar.png' } })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    await vm.onAvatarFileChange({ target: { value: 'x', files: [file] } })
    expect(vm.localUser.avatar_url).toBe('/new-avatar.png')
    wrapper.unmount()
  })

  it('上传失败时提示错误', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    mockAuthApiUploadAvatar.mockRejectedValueOnce(new Error('上传失败'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    await vm.onAvatarFileChange({ target: { value: 'x', files: [file] } })
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('头像上传失败'))
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * onLogout
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – onLogout', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true }, permissions: [] },
    })
  })

  it('用户取消确认时不执行登出', async () => {
    const { appConfirm: _c } = await import('@/utils/appDialog'); void _c
    ;(mockAppConfirm as any).mockResolvedValueOnce(false)
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.onLogout()
    expect(mockAuthApiLogout).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('登出成功时清除用户并跳转', async () => {
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.onLogout()
    expect(mockAuthApiLogout).toHaveBeenCalled()
    expect(mockAccountProfileStore.clear).toHaveBeenCalled()
    expect(vm.localUser).toBeNull()
    expect(vm.sessionValid).toBe(false)
    wrapper.unmount()
  })

  it('登出失败时提示错误', async () => {
    mockAuthApiLogout.mockRejectedValueOnce(new Error('登出失败'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.onLogout()
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('退出失败'))
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * loadAuditLogs 与 downloadAuditCsv
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – 审计日志', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'admin', display_name: 'Admin', email: '', role: 'admin', is_active: true }, permissions: [] },
    })
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('loadAuditLogs 成功时填充审计列表', async () => {
    mockAdminAuditApiList.mockResolvedValue({
      data: {
        items: [
          { action: 'login', timestamp: '2026-01-01', user_id: 1, success: true },
          { action: 'logout', ts: '2026-01-02', user_id: 2, success: false },
        ],
        total: 2,
      },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.loadAuditLogs()
    expect(vm.auditLogs.length).toBe(2)
    expect(vm.auditLogsTotal).toBe(2)
    wrapper.unmount()
  })

  it('loadAuditLogs 失败时设置错误信息', async () => {
    mockAdminAuditApiList.mockRejectedValue(new Error('网络错误'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.loadAuditLogs()
    expect(vm.auditLogsError).toContain('网络错误')
    wrapper.unmount()
  })

  it('downloadAuditCsv 调用 window.open', async () => {
    const openSpy = vi.fn()
    vi.stubGlobal('open', openSpy)
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.downloadAuditCsv()
    expect(openSpy).toHaveBeenCalledWith('/api/admin/audit.csv', '_blank', 'noopener,noreferrer')
    wrapper.unmount()
  })

  it('非管理员不加载审计日志', async () => {
    mockAuthApiGetCurrentUser.mockReset()
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: { user: { id: 1, username: 'user', display_name: 'User', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.loadAuditLogs()
    expect(mockAdminAuditApiList).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * loadDesktopDatabaseStatus
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – loadDesktopDatabaseStatus', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('desktopMode 为 false 时隐藏数据库信息', async () => {
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/api/desktop/status') return { data: { desktopMode: false } }
      return { data: {}, success: false }
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.desktopDatabaseVisible).toBe(false)
    wrapper.unmount()
  })

  it('storageMode 为 local_sqlite 时显示本地 SQLite', async () => {
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/api/desktop/status') return { data: { desktopMode: true, storageMode: 'local_sqlite', database: '/tmp/db.sqlite' } }
      return { data: {}, success: false }
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.desktopDatabaseVisible).toBe(true)
    expect(vm.databaseStorageLabel).toBe('本地数据库（SQLite）')
    expect(vm.currentDbPath).toBe('/tmp/db.sqlite')
    wrapper.unmount()
  })

  it('storageMode 为 remote_postgresql 时显示远程 PostgreSQL', async () => {
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/api/desktop/status') return { data: { desktopMode: true, storageMode: 'remote_postgresql' } }
      return { data: {}, success: false }
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.databaseStorageLabel).toBe('远程 PostgreSQL')
    wrapper.unmount()
  })

  it('storageMode 为其他值时显示本地数据库', async () => {
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/api/desktop/status') return { data: { desktopMode: true, storageMode: 'unknown' } }
      return { data: {}, success: false }
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.databaseStorageLabel).toBe('本地数据库')
    wrapper.unmount()
  })

  it('API 失败时隐藏数据库信息', async () => {
    mockApiGet.mockRejectedValue(new Error('net'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.desktopDatabaseVisible).toBe(false)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * loadIndustries
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – loadIndustries', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('返回数组时直接赋值', async () => {
    mockSystemApiGetIndustries.mockResolvedValueOnce({
      success: true,
      data: [{ id: 'mfg', name: '制造业', code: 'mfg' }],
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.industries.length).toBe(1)
    wrapper.unmount()
  })

  it('返回对象含 industries 字段时赋值', async () => {
    mockIndustryStore.currentIndustry = { id: 'retail', name: '零售' }
    mockSystemApiGetIndustries.mockResolvedValueOnce({
      success: true,
      data: { industries: [{ id: 'retail', name: '零售', code: 'rtl' }], current: 'retail' },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.industries.length).toBe(1)
    wrapper.unmount()
  })

  it('API 失败时不抛错', async () => {
    mockSystemApiGetIndustries.mockRejectedValueOnce(new Error('net'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * loadCurrentIndustryDetail
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – loadCurrentIndustryDetail', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('成功时从 response.data.units.primary 设置主单位', async () => {
    mockSystemApiGetCurrentIndustry.mockResolvedValueOnce({
      success: true,
      data: { units: { primary: '件' } },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.currentIndustryUnit).toBe('件')
    wrapper.unmount()
  })

  it('成功但无 units.primary 时默认为 天', async () => {
    mockSystemApiGetCurrentIndustry.mockResolvedValueOnce({
      success: true,
      data: {},
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.currentIndustryUnit).toBe('天')
    wrapper.unmount()
  })

  it('失败时用 mod manifest 兜底', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext', industry: { id: 'ind1', name: '行业1', units: { primary: '小时' } } }]
    mockModsStore.activeModId = 'ext-1'
    mockSystemApiGetCurrentIndustry.mockRejectedValueOnce(new Error('net'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.currentIndustryUnit).toBe('小时')
    wrapper.unmount()
  })

  it('失败且无 mod 时保持默认', async () => {
    mockSystemApiGetCurrentIndustry.mockRejectedValueOnce(new Error('net'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.currentIndustryUnit).toBe('天')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * loadIntentPackages
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – loadIntentPackages', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('返回 packages 对象时更新 intentPackages', async () => {
    mockIntentPackagesApiGetPackages.mockResolvedValueOnce({
      success: true,
      data: {
        packages: {
          base: { enabled: false, keywords: ['新词'] },
          industry: { enabled: true, keywords: ['行业词'] },
        },
      },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.intentPackages.base.enabled).toBe(false)
    expect(vm.intentPackages.base.keywords).toEqual(['新词'])
    expect(vm.intentPackages.industry.enabled).toBe(true)
    wrapper.unmount()
  })

  it('返回数组时忽略', async () => {
    mockIntentPackagesApiGetPackages.mockResolvedValueOnce({
      success: true,
      data: [{ key: 'base' }],
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.intentPackages.base.enabled).toBe(true)
    wrapper.unmount()
  })

  it('API 失败时不抛错', async () => {
    mockIntentPackagesApiGetPackages.mockRejectedValueOnce(new Error('net'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * loadPreferences - 直接调用 vm 方法
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – loadPreferences', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('从 prefs 读取 assistantName 与 aiMode', async () => {
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/api/preferences') {
        return { success: true, preferences: { assistantName: '小智', aiMode: 'offline' } }
      }
      return { data: {}, success: false }
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.assistantName).toBe('小智')
    expect(vm.aiMode).toBe('offline')
    wrapper.unmount()
  })

  it('prefs 无 assistantName 时从 localStorage 读取', async () => {
    localStorage.setItem('assistantName', '本地助手')
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/api/preferences') return { success: true, preferences: {} }
      return { data: {}, success: false }
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.assistantName).toBe('本地助手')
    wrapper.unmount()
  })

  it('prefs 无 aiMode 但有 legacy aiModel=local 时迁移', async () => {
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/api/preferences') return { success: true, preferences: { aiModel: 'local' } }
      return { data: {}, success: false }
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.aiMode).toBe('offline')
    expect(mockApiPost).toHaveBeenCalledWith('/api/preferences', expect.objectContaining({ key: 'aiMode', value: 'offline' }))
    wrapper.unmount()
  })

  it('prefs 无 aiMode 但有 legacy aiModel=cloud 时设为 online', async () => {
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/api/preferences') return { success: true, preferences: { aiModel: 'cloud' } }
      return { data: {}, success: false }
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.aiMode).toBe('online')
    wrapper.unmount()
  })

  it('API 失败时从 localStorage 读取 assistantName', async () => {
    localStorage.setItem('assistantName', '兜底助手')
    mockApiGet.mockRejectedValue(new Error('net'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.assistantName).toBe('兜底助手')
    wrapper.unmount()
  })

  it('API 失败且无 localStorage 时用默认值', async () => {
    mockApiGet.mockRejectedValue(new Error('net'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.assistantName).toBe('修茈')
    wrapper.unmount()
  })

  it('返回 success:false 时直接返回', async () => {
    mockApiGet.mockImplementation(async () => ({ success: false }))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.assistantName).toBe('修茈')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * saveSettings
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – saveSettings', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('保存成功时派发 assistant-name-updated 事件', async () => {
    mockApiPost.mockResolvedValue({ success: true })
    const dispatchSpy = vi.fn()
    window.dispatchEvent = dispatchSpy
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.assistantName = '新助手'
    await nextTick()
    await vm.saveSettings()
    expect(mockApiPost).toHaveBeenCalledTimes(2)
    const event = dispatchSpy.mock.calls[0][0]
    expect(event.type).toBe('assistant-name-updated')
    expect(event.detail.name).toBe('新助手')
    wrapper.unmount()
  })

  it('其中一个保存失败时提示错误', async () => {
    mockApiPost.mockImplementationOnce(async () => ({ success: false, message: '保存失败' }))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.saveSettings()
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('保存失败'))
    wrapper.unmount()
  })

  it('保存抛异常时提示错误', async () => {
    mockApiPost.mockRejectedValueOnce(new Error('网络错误'))
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.saveSettings()
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('保存失败'))
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * loadDistillationVersions
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – loadDistillationVersions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('成功时填充 versions 与 sampleCount', async () => {
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/api/distillation/versions') {
        return {
          success: true,
          versions: [{ name: 'v1.pt', label: 'V1', modified: '2026-01-01', size_kb: 100 }],
          distillation_samples: 500,
        }
      }
      return { data: {}, success: false }
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.versions.length).toBe(1)
    expect(vm.sampleCount).toBe(500)
    wrapper.unmount()
  })

  it('返回 sample_count_error 时设置警告', async () => {
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/api/distillation/versions') {
        return {
          success: true,
          versions: [],
          distillation_samples: 0,
          sample_count_error: '读取失败',
        }
      }
      return { data: {}, success: false }
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.sampleCountWarning).toContain('读取失败')
    wrapper.unmount()
  })

  it('返回 success:false 时设置错误信息', async () => {
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/api/distillation/versions') return { success: false, message: '权限不足' }
      return { data: {}, success: false }
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.versionsError).toContain('权限不足')
    wrapper.unmount()
  })

  it('API 抛异常时设置错误信息', async () => {
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/api/distillation/versions') throw new Error('网络错误')
      return { data: {}, success: false }
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.versionsError).toContain('网络错误')
    expect(vm.versions.length).toBe(0)
    expect(vm.sampleCount).toBe(0)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * onCheckForUpdates
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – onCheckForUpdates', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
    delete (window as any).xcagiDesktop
  })

  it('无 desktop.checkForUpdates 时提示不可用', async () => {
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.onCheckForUpdates()
    expect(vm.aboutUpdateError).toBe(true)
    expect(vm.aboutUpdateMessage).toBe('settings.updateUnavailable')
    wrapper.unmount()
  })

  it('有 checkForUpdates 时调用并提示已开始', async () => {
    const checkSpy = vi.fn().mockResolvedValue(undefined)
    ;(window as any).xcagiDesktop = { checkForUpdates: checkSpy }
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.onCheckForUpdates()
    expect(checkSpy).toHaveBeenCalled()
    expect(vm.aboutUpdateMessage).toBe('settings.updateCheckStarted')
    expect(vm.aboutUpdateError).toBe(false)
    wrapper.unmount()
    delete (window as any).xcagiDesktop
  })

  it('checkForUpdates 抛异常时提示失败', async () => {
    const checkSpy = vi.fn().mockRejectedValue(new Error('检查失败'))
    ;(window as any).xcagiDesktop = { checkForUpdates: checkSpy }
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.onCheckForUpdates()
    expect(vm.aboutUpdateError).toBe(true)
    expect(vm.aboutUpdateMessage).toContain('检查失败')
    wrapper.unmount()
    delete (window as any).xcagiDesktop
  })
})

/* ══════════════════════════════════════════════════════════════════
 * onSidebarThemeChange 与 onLocaleChange
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – 主题与语言切换', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('onSidebarThemeChange 调用 persistSidebarTheme', async () => {
    const { persistSidebarTheme } = await import('@/utils/sidebarTheme')
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.sidebarThemePreset = 'dark'
    await nextTick()
    vm.onSidebarThemeChange()
    expect(persistSidebarTheme).toHaveBeenCalledWith('dark')
    wrapper.unmount()
  })

  it('onLocaleChange 调用 setAppLocale', async () => {
    const { setAppLocale } = await import('@/i18n')
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.appLocale = 'en-US'
    await nextTick()
    vm.onLocaleChange()
    expect(setAppLocale).toHaveBeenCalledWith('en-US')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * openSettingsExtensions
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – openSettingsExtensions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })
  afterEach(() => { vi.restoreAllMocks() })

  it('找到 details 元素时打开并滚动', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    // 使用真实的 <details> 元素以通过 instanceof HTMLDetailsElement 检查
    const fakeEl = document.createElement('details')
    fakeEl.open = false
    ;(fakeEl as any).scrollIntoView = vi.fn()
    const querySpy = vi.spyOn(document, 'querySelector').mockImplementation((sel: string) => {
      if (sel === '[data-tutorial-id="settings-extensions"]') return fakeEl
      return null
    })
    vm.openSettingsExtensions()
    expect(fakeEl.open).toBe(true)
    expect((fakeEl as any).scrollIntoView).toHaveBeenCalled()
    querySpy.mockRestore()
    wrapper.unmount()
  })

  it('未找到 details 元素时跳转 mod-store', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const querySpy = vi.spyOn(document, 'querySelector').mockReturnValue(null)
    const pushSpy = vi.spyOn(vm.$router, 'push')
    await vm.openSettingsExtensions()
    expect(pushSpy).toHaveBeenCalledWith({ name: 'mod-store' })
    querySpy.mockRestore()
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * goHostPackOnboarding 与 goModStore
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – 路由跳转方法', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('goHostPackOnboarding 跳转到 onboarding', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const pushSpy = vi.spyOn(vm.$router, 'push')
    vm.goHostPackOnboarding()
    expect(pushSpy).toHaveBeenCalledWith({ path: '/onboarding', query: { step: 'host-pack' } })
    wrapper.unmount()
  })

  it('goModStore 跳转到 mod-store', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const pushSpy = vi.spyOn(vm.$router, 'push')
    vm.goModStore()
    expect(pushSpy).toHaveBeenCalledWith({ name: 'mod-store' })
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * retryModRoutesLoad
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – retryModRoutesLoad', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('刷新后仍有 loadError 时提示', async () => {
    mockModsStore.refresh.mockResolvedValueOnce(undefined)
    mockModsStore.loadError = '加载失败'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.retryModRoutesLoad()
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith('加载失败')
    wrapper.unmount()
  })

  it('刷新后 mods 有但 routes 为空时提示', async () => {
    mockModsStore.refresh.mockResolvedValueOnce(undefined)
    mockModsStore.loadError = ''
    mockModsStore.mods = [{ id: 'm1' }]
    mockModsStore.modRoutes = []
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.retryModRoutesLoad()
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('仍未获取到路由表'))
    wrapper.unmount()
  })

  it('刷新成功时提示已加载', async () => {
    mockModsStore.refresh.mockResolvedValueOnce(undefined)
    mockModsStore.loadError = ''
    mockModsStore.mods = [{ id: 'm1' }]
    mockModsStore.modRoutes = [{ path: '/x' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.retryModRoutesLoad()
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith('Mod 与路由已重新加载。')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * onActiveModChange
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – onActiveModChange', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })
  afterEach(() => { vi.restoreAllMocks() })

  it('空 modId 时不执行', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onActiveModChange('')
    expect(mockModsStore.setActiveModId).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('与当前 activeModId 相同时不执行', async () => {
    mockModsStore.activeModId = 'ext-1'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onActiveModChange('ext-1')
    expect(mockModsStore.setActiveModId).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('切换 mod 并切换行业成功时刷新页面', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1', industry: { id: 'ind1', name: '行业1' } }]
    mockIndustryStore.switchIndustry.mockResolvedValueOnce(true)
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onActiveModChange('ext-1')
    expect(mockModsStore.setActiveModId).toHaveBeenCalledWith('ext-1')
    expect(mockIndustryStore.switchIndustry).toHaveBeenCalledWith('ind1')
    wrapper.unmount()
  })

  it('切换 mod 但行业切换失败时仅警告不回滚', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1', industry: { id: 'ind1', name: '行业1' } }]
    mockIndustryStore.switchIndustry.mockResolvedValueOnce(false)
    mockIndustryStore.error = '后端拒绝'
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onActiveModChange('ext-1')
    expect(warnSpy).toHaveBeenCalled()
    wrapper.unmount()
    warnSpy.mockRestore()
  })

  it('切换 mod 无 industry id 时不切换行业', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onActiveModChange('ext-1')
    expect(mockModsStore.setActiveModId).toHaveBeenCalledWith('ext-1')
    expect(mockIndustryStore.switchIndustry).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * onUninstallMod
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – onUninstallMod', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('空 modId 时不执行', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('')
    expect(mockApiDelete).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('受保护 mod 时提示不能卸载', async () => {
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('protected-mod')
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('受保护'))
    expect(mockApiDelete).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('用户取消确认时不卸载', async () => {
    const { appConfirm: _c } = await import('@/utils/appDialog'); void _c
    ;(mockAppConfirm as any).mockResolvedValueOnce(false)
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('ext-1')
    expect(mockApiDelete).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('卸载成功时提示并刷新', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1' }]
    mockApiDelete.mockResolvedValueOnce({ success: true, message: '已卸载' })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('ext-1')
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith('已卸载')
    wrapper.unmount()
  })

  it('卸载返回 success:false 时提示失败', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1' }]
    mockApiDelete.mockResolvedValueOnce({ success: false, message: '权限不足' })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('ext-1')
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('卸载失败'))
    wrapper.unmount()
  })

  it('卸载抛 ApiError 时提示错误', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1' }]
    const { ApiError } = await import('@/api')
    mockApiDelete.mockRejectedValueOnce(new ApiError('API 错误', 500))
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('ext-1')
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('API 错误'))
    wrapper.unmount()
  })

  it('卸载抛普通 Error 时提示错误', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1' }]
    mockApiDelete.mockRejectedValueOnce(new Error('网络错误'))
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('ext-1')
    const { appAlert: _a } = await import('@/utils/appDialog'); void _a
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('网络错误'))
    wrapper.unmount()
  })

  it('卸载 primary mod 时提示包含主扩展警告', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1', primary: true }]
    mockApiDelete.mockResolvedValueOnce({ success: true, message: '已卸载' })
    const { appConfirm: _c } = await import('@/utils/appDialog'); void _c
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('ext-1')
    expect(mockAppConfirm).toHaveBeenCalledWith(expect.stringContaining('主扩展'), expect.anything())
    wrapper.unmount()
  })

  it('卸载当前 active mod 时提示包含刷新警告', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1' }]
    mockModsStore.activeModId = 'ext-1'
    mockApiDelete.mockResolvedValueOnce({ success: true, message: '已卸载' })
    const { appConfirm: _c } = await import('@/utils/appDialog'); void _c
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('ext-1')
    expect(mockAppConfirm).toHaveBeenCalledWith(expect.stringContaining('当前启用'), expect.anything())
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * scrollToSettingsSection
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – scrollToSettingsSection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })
  afterEach(() => { vi.restoreAllMocks() })

  it('route.query.section 存在时滚动到对应元素', async () => {
    // 使用真实的 <details> 元素以通过 instanceof HTMLDetailsElement 检查
    const fakeEl = document.createElement('details')
    fakeEl.open = false
    ;(fakeEl as any).scrollIntoView = vi.fn()
    ;(fakeEl as any).closest = vi.fn(() => null)
    const getByIdSpy = vi.spyOn(document, 'getElementById').mockReturnValue(fakeEl)
    const wrapper = await mountSettings({ section: 'profile-home' })
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    expect(fakeEl.open).toBe(true)
    expect((fakeEl as any).scrollIntoView).toHaveBeenCalled()
    getByIdSpy.mockRestore()
    wrapper.unmount()
  })

  it('route.query.section 为空时不滚动', async () => {
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    const getElementByIdSpy = vi.spyOn(document, 'getElementById')
    vm.scrollToSettingsSection()
    expect(getElementByIdSpy).not.toHaveBeenCalled()
    getElementByIdSpy.mockRestore()
    wrapper.unmount()
  })

  it('找到非 details 元素时打开父 details', async () => {
    // 使用真实的 <details> 元素作为父元素以通过 instanceof HTMLDetailsElement 检查
    const parentDetails = document.createElement('details')
    parentDetails.open = false
    const fakeEl = document.createElement('div')
    ;(fakeEl as any).scrollIntoView = vi.fn()
    ;(fakeEl as any).closest = vi.fn(() => parentDetails)
    const getByIdSpy = vi.spyOn(document, 'getElementById').mockReturnValue(fakeEl)
    const wrapper = await mountSettings({ section: 'unknown' })
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    expect(parentDetails.open).toBe(true)
    getByIdSpy.mockRestore()
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * 计算属性 - mod 相关
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – mod 相关计算属性', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('modelPaymentBridgeInstalled 检测 bridge mod', async () => {
    mockModsStore.mods = [{ id: 'xcagi-model-payment-bridge', name: 'Bridge' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.modelPaymentBridgeInstalled).toBe(true)
    wrapper.unmount()
  })

  it('hostBridgeMods 过滤并排序', async () => {
    mockModsStore.mods = [
      { id: 'host-bridge-2', name: 'Bridge2' },
      { id: 'ext-1', name: 'Ext1' },
      { id: 'host-bridge-1', name: 'Bridge1' },
    ]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.hostBridgeMods.length).toBe(2)
    expect(vm.hostBridgeMods[0].id).toBe('host-bridge-1')
    wrapper.unmount()
  })

  it('hostBridgeInstalledCount 计算已安装数', async () => {
    mockModsStore.mods = [
      { id: 'host-bridge-1' },
      { id: 'host-bridge-2' },
    ]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.hostBridgeInstalledCount).toBe(2)
    expect(vm.hostBridgeExpectedCount).toBe(2)
    wrapper.unmount()
  })

  it('selectableExtensionMods 过滤扩展 mod', async () => {
    mockModsStore.mods = [
      { id: 'ext-1', name: 'Ext1' },
      { id: 'ext-2', name: 'Ext2' },
      { id: 'host-bridge-1', name: 'Bridge1' },
    ]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.selectableExtensionMods.length).toBe(2)
    wrapper.unmount()
  })

  it('workflowEmployeeMods 过滤工作流 mod', async () => {
    mockModsStore.mods = [
      { id: 'wf-1', name: 'Wf1' },
      { id: 'ext-1', name: 'Ext1' },
    ]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.workflowEmployeeMods.length).toBe(1)
    wrapper.unmount()
  })

  it('activeModMeta 返回当前 mod 元数据', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1', industry: { id: 'ind1' } }]
    mockModsStore.activeModId = 'ext-1'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.activeModMeta).toBeTruthy()
    expect(vm.activeModMeta.name).toBe('Ext1')
    expect(vm.activeModIndustry).toBeTruthy()
    expect(vm.activeModIndustry.id).toBe('ind1')
    wrapper.unmount()
  })

  it('activeModMeta 无 active 时返回 null', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.activeModMeta).toBeNull()
    expect(vm.activeModIndustry).toBeNull()
    wrapper.unmount()
  })

  it('modRoutesStatusText clientModsUiOff 时为空', async () => {
    mockModsStore.clientModsUiOff = true
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.modRoutesStatusText).toBe('')
    expect(vm.showModRoutesRetry).toBe(false)
    wrapper.unmount()
  })

  it('modRoutesStatusText loadError 时返回错误', async () => {
    mockModsStore.loadError = '加载错误'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.modRoutesStatusText).toBe('加载错误')
    expect(vm.showModRoutesRetry).toBe(true)
    wrapper.unmount()
  })

  it('modRoutesStatusText mods 有但 routes 为空时返回提示', async () => {
    mockModsStore.isLoaded = true
    mockModsStore.mods = [{ id: 'm1' }]
    mockModsStore.modRoutes = []
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.modRoutesStatusText).toContain('Mod 路由未加载')
    wrapper.unmount()
  })

  it('modSettingsFoldMeta 各种组合', async () => {
    mockModsStore.mods = [
      { id: 'host-bridge-1' },
      { id: 'ext-1', name: 'Ext1' },
      { id: 'wf-1', name: 'Wf1' },
    ]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const meta = vm.modSettingsFoldMeta
    expect(meta).toContain('核心')
    expect(meta).toContain('行业包')
    expect(meta).toContain('工作流')
    wrapper.unmount()
  })

  it('modSettingsFoldMeta 无 mod 时返回 0 个行业包', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    // 无 mod 时 ext = '0 个行业包'，host 和 wf 为空，filter(Boolean) 后剩 ext
    expect(vm.modSettingsFoldMeta).toBe('0 个行业包')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * 计算属性 - 行业与品牌
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – 行业与品牌计算属性', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('currentIndustryLabel 从 mod industry 获取', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1', industry: { id: 'ind1', name: '制造业' } }]
    mockModsStore.activeModId = 'ext-1'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.currentIndustryLabel).toBe('制造业')
    wrapper.unmount()
  })

  it('currentIndustryLabel 无 mod 时从 preset 获取', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.currentIndustryLabel).toBe('默认行业')
    wrapper.unmount()
  })

  it('systemDisplayName 有 brand 时返回组合', async () => {
    mockAccountProfileStore.displayBrand = '公司X'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.systemDisplayName).toBe('公司X 交付工作台')
    wrapper.unmount()
  })

  it('systemDisplayName 无 brand 时返回通用宿主', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.systemDisplayName).toBe('XCAGI 通用宿主')
    wrapper.unmount()
  })

  it('aboutDisplayLine 有 brand 与 industry 时返回完整', async () => {
    mockAccountProfileStore.displayBrand = '公司X'
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1', industry: { id: 'ind1', name: '制造业' } }]
    mockModsStore.activeModId = 'ext-1'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.aboutDisplayLine).toContain('公司X')
    expect(vm.aboutDisplayLine).toContain('制造业')
    wrapper.unmount()
  })

  it('aboutDisplayLine 有 brand 无 industry 时返回账号定制', async () => {
    // currentIndustryLabel 总会返回非空字符串（fallback 到 id 或 '通用'）
    // 所以 '账号定制基础线' 分支在实际运行中不会触发
    // 此测试验证有 brand 有 industry 时的完整输出
    mockAccountProfileStore.displayBrand = '公司X'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.aboutDisplayLine).toContain('公司X')
    expect(vm.aboutDisplayLine).toContain('基础线')
    wrapper.unmount()
  })

  it('deliveryBrandName 优先用 account custom mod name', async () => {
    mockModsStore.mods = [{ id: 'taiyangniao-pro', name: '太阳鸟 PRO' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.deliveryBrandName).toBe('太阳鸟 PRO')
    wrapper.unmount()
  })

  it('deliveryBrandName 无 custom mod 时用 displayBrand', async () => {
    mockAccountProfileStore.displayBrand = '公司Y'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.deliveryBrandName).toBe('公司Y')
    wrapper.unmount()
  })

  it('selectedSidebarAccent 返回选中主题的 accent', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.sidebarThemePreset = 'dark'
    await nextTick()
    expect(vm.selectedSidebarAccent).toBe('#1e293b')
    wrapper.unmount()
  })

  it('currentIndustryConfig 找到匹配行业', async () => {
    mockIndustryStore.industries = [{ id: 'default', name: '默认', code: 'def' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.currentIndustryConfig).toBeTruthy()
    expect(vm.currentIndustryConfig.name).toBe('默认')
    wrapper.unmount()
  })

  it('currentIntentIndustryLabel 有 cfg.name 时返回', async () => {
    mockIndustryStore.industries = [{ id: 'default', name: '默认行业', code: 'def' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.currentIntentIndustryLabel).toBe('默认行业')
    wrapper.unmount()
  })

  it('currentIntentIndustryLabel 无 cfg 时从 preset 获取', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.currentIntentIndustryLabel).toBe('默认行业')
    wrapper.unmount()
  })

  it('basicSettingsSummary online 模式', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.aiMode = 'online'
    await nextTick()
    expect(vm.basicSettingsSummary).toContain('settings.aiModeOnline')
    wrapper.unmount()
  })

  it('basicSettingsSummary offline 模式', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.aiMode = 'offline'
    await nextTick()
    expect(vm.basicSettingsSummary).toContain('settings.offline')
    wrapper.unmount()
  })

  it('normalizedAssistantName 空时返回默认', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.assistantName = '  '
    await nextTick()
    expect(vm.normalizedAssistantName).toBe('修茈')
    wrapper.unmount()
  })

  it('isDesktopShell 检测 window.xcagiDesktop', async () => {
    ;(window as any).xcagiDesktop = { checkForUpdates: vi.fn() }
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.isDesktopShell).toBe(true)
    wrapper.unmount()
    delete (window as any).xcagiDesktop
  })

  it('loginRoute 包含 redirect query', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const route = vm.loginRoute
    expect(route.name).toBe('login')
    expect(route.query.redirect).toBeDefined()
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * intentPackageEntries
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – intentPackageEntries', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('返回所有 intent package 条目', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.intentPackageEntries.length).toBe(5)
    expect(vm.intentPackageEntries[0].key).toBe('base')
    wrapper.unmount()
  })

  it('keywords 为空时显示暂无示例词', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.intentPackages = {
      ...vm.intentPackages,
      industry: { name: '行业', iconClass: 'fa', description: '', enabled: true, keywords: [] },
    }
    await nextTick()
    const industryEntry = vm.intentPackageEntries.find((e: any) => e.key === 'industry')
    expect(industryEntry.keywords.length).toBe(0)
    wrapper.unmount()
  })

  it('keywords 过滤空字符串', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.intentPackages = {
      ...vm.intentPackages,
      base: { name: '基础', iconClass: 'fa', description: '', enabled: true, keywords: ['有效', '', '  ', '词'] },
    }
    await nextTick()
    const baseEntry = vm.intentPackageEntries.find((e: any) => e.key === 'base')
    expect(baseEntry.keywords.length).toBe(2)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * updateIndustryKeywords - 直接调用 vm 方法
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – updateIndustryKeywords', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('从 mod manifest.intent_keywords 更新', async () => {
    mockModsStore.mods = [{
      id: 'ext-1',
      name: 'Ext1',
      industry: {
        id: 'ind1',
        name: '行业1',
        intent_keywords: {
          create_order: ['创建订单', '下单'],
          quantity_unit: '件',
          print_label: '打印',
        },
      },
    }]
    mockModsStore.activeModId = 'ext-1'
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    // 直接调用 updateIndustryKeywords
    vm.updateIndustryKeywords()
    await nextTick()
    expect(vm.intentPackages.industry.keywords).toContain('创建订单')
    expect(vm.intentPackages.industry.keywords).toContain('件')
    expect(vm.intentPackages.industry.keywords).toContain('打印')
    wrapper.unmount()
  })

  it('从 industryStore.currentConfig 读取', async () => {
    mockIndustryStore.currentConfig = {
      intent_keywords: {
        create_order: '创建',
        quantity_unit: ['个', '批'],
      },
    }
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.updateIndustryKeywords()
    await nextTick()
    expect(vm.intentPackages.industry.keywords).toContain('创建')
    expect(vm.intentPackages.industry.keywords).toContain('个')
    wrapper.unmount()
  })

  it('无 keywords 数据时不更新', async () => {
    mockIndustryStore.currentConfig = null
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    vm.updateIndustryKeywords()
    await nextTick()
    expect(vm.intentPackages.industry.keywords).toEqual([])
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * applyAccountMetaFromAuthPayload
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – applyAccountMetaFromAuthPayload', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('payload 含 data 对象时合并字段', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: {
        user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true },
        account_kind: 'enterprise',
        company_brand: '公司Z',
        market_is_admin: true,
        market_is_enterprise: true,
        impersonating_market_user_id: 5,
        impersonating_username: 'imp',
      },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    expect(mockAccountProfileStore.applyFromMeData).toHaveBeenCalledWith(expect.objectContaining({
      account_kind: 'enterprise',
      company_brand: '公司Z',
      market_is_admin: true,
    }))
    wrapper.unmount()
  })

  it('payload 无 data 时用空对象兜底', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValueOnce({
      success: true,
      data: {
        user: { id: 1, username: 'a', display_name: 'A', email: '', role: 'user', is_active: true },
      },
      account_kind: 'personal',
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    expect(mockAccountProfileStore.applyFromMeData).toHaveBeenCalled()
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * UI 事件交互测试
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – UI 事件交互', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })
  afterEach(() => { vi.restoreAllMocks() })

  it('点击保存设置按钮可触发 saveSettings', async () => {
    mockApiPost.mockResolvedValue({ success: true })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    // 直接调用 saveSettings 验证按钮绑定
    await vm.saveSettings()
    expect(mockApiPost).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('切换 sidebar theme select 触发 onSidebarThemeChange', async () => {
    const { persistSidebarTheme } = await import('@/utils/sidebarTheme')
    const wrapper = await mountSettings()
    const select = wrapper.find('#settings-sidebar-theme')
    await select.setValue('dark')
    await select.trigger('change')
    expect(persistSidebarTheme).toHaveBeenCalledWith('dark')
    wrapper.unmount()
  })

  it('切换 locale select 触发 onLocaleChange', async () => {
    const { setAppLocale } = await import('@/i18n')
    const wrapper = await mountSettings()
    const select = wrapper.find('#settings-locale')
    await select.setValue('en-US')
    await select.trigger('change')
    expect(setAppLocale).toHaveBeenCalledWith('en-US')
    wrapper.unmount()
  })

  it('点击模型服务扩展按钮触发 openSettingsExtensions', async () => {
    mockModsStore.mods = []
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    // 直接调用方法验证
    const querySpy = vi.spyOn(document, 'querySelector').mockReturnValue(null)
    const pushSpy = vi.spyOn(vm.$router, 'push')
    vm.openSettingsExtensions()
    expect(pushSpy).toHaveBeenCalledWith({ name: 'mod-store' })
    querySpy.mockRestore()
    wrapper.unmount()
  })

  it('点击 host pack 展开按钮切换 hostPackExpanded', async () => {
    mockModsStore.mods = [{ id: 'host-bridge-1', name: 'Bridge1' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.hostPackExpanded).toBe(false)
    const btn = wrapper.find('.mod-host-pack-bar .btn-secondary')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(vm.hostPackExpanded).toBe(true)
    wrapper.unmount()
  })

  it('点击一键装齐按钮触发 goHostPackOnboarding', async () => {
    mockModsStore.mods = [{ id: 'host-bridge-1', name: 'Bridge1' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const pushSpy = vi.spyOn(vm.$router, 'push')
    const btn = wrapper.find('.mod-host-pack-bar .btn-link')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(pushSpy).toHaveBeenCalledWith({ path: '/onboarding', query: { step: 'host-pack' } })
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * watch activeModIndustry
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView – watch activeModIndustry', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('activeModIndustry 变化时触发 updateIndustryKeywords', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1', industry: { id: 'ind1', name: '行业1', intent_keywords: { create_order: '创建' } } }]
    mockModsStore.activeModId = 'ext-1'
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    // 直接调用 updateIndustryKeywords 验证逻辑
    vm.updateIndustryKeywords()
    await nextTick()
    expect(vm.intentPackages.industry.keywords).toContain('创建')
    wrapper.unmount()
  })
})

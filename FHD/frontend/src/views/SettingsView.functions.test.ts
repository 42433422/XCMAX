/**
 * SettingsView.vue 函数补全测试
 * 重点覆盖：memoryV2 系列、persy 系列、retryModRoutesLoad、onActiveModChange、
 * onUninstallMod、scrollToSettingsSection、syncProfileDraftsFromUser、
 * hydrateUserFromSessionValidate、downloadAuditCsv、errorMessage 等未覆盖函数
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

/* memoryV2Api mocks */
const mockMemoryV2List = vi.fn().mockResolvedValue({ success: true, memories: [], summary: { total: 0, by_status: {}, by_type: {} }, planner_context: '' })
const mockMemoryV2Summary = vi.fn().mockResolvedValue({ success: true, summary: { total: 0, by_status: {}, by_type: {} }, planner_context: '' })
const mockMemoryV2CreateCandidate = vi.fn().mockResolvedValue({ success: true })
const mockMemoryV2Confirm = vi.fn().mockResolvedValue({ success: true })
const mockMemoryV2Reject = vi.fn().mockResolvedValue({ success: true })
const mockMemoryV2Correct = vi.fn().mockResolvedValue({ success: true })
const mockMemoryV2Remove = vi.fn().mockResolvedValue({ success: true })

/* butlerProfileApi mocks */
const mockButlerProfileGet = vi.fn().mockResolvedValue({ success: true, profile: null })
const mockButlerProfileInfer = vi.fn().mockResolvedValue({ success: true, profile: null, inference: { reasons: [] } })

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

vi.mock('@/api/memoryV2', () => ({
  memoryV2Api: {
    list: (...args: unknown[]) => mockMemoryV2List(...args),
    summary: (...args: unknown[]) => mockMemoryV2Summary(...args),
    createCandidate: (...args: unknown[]) => mockMemoryV2CreateCandidate(...args),
    confirm: (...args: unknown[]) => mockMemoryV2Confirm(...args),
    reject: (...args: unknown[]) => mockMemoryV2Reject(...args),
    correct: (...args: unknown[]) => mockMemoryV2Correct(...args),
    remove: (...args: unknown[]) => mockMemoryV2Remove(...args),
  },
}))

vi.mock('@/api/butlerProfile', () => ({
  butlerProfileApi: {
    get: (...args: unknown[]) => mockButlerProfileGet(...args),
    infer: (...args: unknown[]) => mockButlerProfileInfer(...args),
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
  modsForWorkflowUi: [] as unknown[],
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
  mockIndustryStore.loading = false
  mockIndustryStore.error = null
  mockModsStore.mods = []
  mockModsStore.activeModId = ''
  mockModsStore.clientModsUiOff = false
  mockModsStore.loadError = ''
  mockModsStore.isLoaded = true
  mockModsStore.modRoutes = []
  mockAccountProfileStore.profile = null
  mockAccountProfileStore.isLoggedIn = false
  mockAccountProfileStore.loading = false
  mockAccountProfileStore.companyBrand = ''
  mockAccountProfileStore.displayBrand = ''
  mockAccountProfileStore.accountKind = 'personal'
  mockAccountProfileStore.isLocalAdmin = false
}

function resetApiMocks() {
  vi.clearAllMocks()
  mockApiGet.mockResolvedValue({ data: {}, success: false })
  mockApiPost.mockResolvedValue({ success: true })
  mockApiDelete.mockResolvedValue({ success: true, message: 'ok' })
  mockAuthApiValidateSession.mockResolvedValue({ success: false })
  mockAuthApiGetCurrentUser.mockResolvedValue({ success: false, data: { user: null, permissions: [] } })
  mockAuthApiLogout.mockResolvedValue({})
  mockAuthApiUpdateCompanyBrand.mockResolvedValue({ success: true })
  mockAuthApiUploadAvatar.mockResolvedValue({ success: true, data: { avatar_url: '/api/auth/avatar' } })
  mockAuthApiUpdateProfile.mockResolvedValue({ success: true, data: { user: null } })
  mockSystemApiGetIndustries.mockResolvedValue({ success: true, data: [] })
  mockSystemApiGetCurrentIndustry.mockResolvedValue({ success: false })
  mockIntentPackagesApiGetPackages.mockResolvedValue({ success: false, data: null })
  mockAdminAuditApiList.mockResolvedValue({ ok: true, data: { items: [], total: 0 } })
  mockMemoryV2List.mockResolvedValue({ success: true, memories: [], summary: { total: 0, by_status: {}, by_type: {} }, planner_context: '' })
  mockMemoryV2Summary.mockResolvedValue({ success: true, summary: { total: 0, by_status: {}, by_type: {} }, planner_context: '' })
  mockMemoryV2CreateCandidate.mockResolvedValue({ success: true })
  mockMemoryV2Confirm.mockResolvedValue({ success: true })
  mockMemoryV2Reject.mockResolvedValue({ success: true })
  mockMemoryV2Correct.mockResolvedValue({ success: true })
  mockMemoryV2Remove.mockResolvedValue({ success: true })
  mockButlerProfileGet.mockResolvedValue({ success: true, profile: null })
  mockButlerProfileInfer.mockResolvedValue({ success: true, profile: null, inference: { reasons: [] } })
}

/* ══════════════════════════════════════════════════════════════════
 * memoryV2 工具函数
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView functions – memoryV2TypeLabel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('返回已知类型的中文标签', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2TypeLabel('preference')).toBe('偏好')
    expect(vm.memoryV2TypeLabel('entity')).toBe('实体')
    expect(vm.memoryV2TypeLabel('episodic')).toBe('任务')
    wrapper.unmount()
  })

  it('未知类型返回类型字符串', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2TypeLabel('unknown')).toBe('unknown')
    wrapper.unmount()
  })

  it('空值返回 未知', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2TypeLabel('')).toBe('未知')
    expect(vm.memoryV2TypeLabel(null)).toBe('未知')
    expect(vm.memoryV2TypeLabel(undefined)).toBe('未知')
    wrapper.unmount()
  })
})

describe('SettingsView functions – memoryV2StatusLabel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('返回已知状态的中文标签', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2StatusLabel('pending')).toBe('待确认')
    expect(vm.memoryV2StatusLabel('active')).toBe('已确认')
    expect(vm.memoryV2StatusLabel('rejected')).toBe('已拒绝')
    expect(vm.memoryV2StatusLabel('deleted')).toBe('已删除')
    expect(vm.memoryV2StatusLabel('all')).toBe('全部')
    wrapper.unmount()
  })

  it('未知状态返回状态字符串', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2StatusLabel('unknown')).toBe('unknown')
    wrapper.unmount()
  })

  it('空值返回 未知', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2StatusLabel('')).toBe('未知')
    expect(vm.memoryV2StatusLabel(null)).toBe('未知')
    wrapper.unmount()
  })
})

describe('SettingsView functions – memoryV2EditableValue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('字符串原样返回', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2EditableValue('hello')).toBe('hello')
    wrapper.unmount()
  })

  it('对象 JSON 序列化', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const result = vm.memoryV2EditableValue({ a: 1, b: 'x' })
    expect(result).toContain('"a": 1')
    expect(result).toContain('"b": "x"')
    wrapper.unmount()
  })

  it('数组 JSON 序列化', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const result = vm.memoryV2EditableValue([1, 2, 3])
    expect(result).toContain('1')
    expect(result).toContain('2')
    wrapper.unmount()
  })

  it('null 返回字符串 null（JSON.stringify 行为）', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2EditableValue(null)).toBe('null')
    wrapper.unmount()
  })

  it('undefined 返回 undefined（JSON.stringify 行为）', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2EditableValue(undefined)).toBeUndefined()
    wrapper.unmount()
  })

  it('数字转字符串', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2EditableValue(42)).toBe('42')
    wrapper.unmount()
  })
})

describe('SettingsView functions – memoryV2DisplayValue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('短字符串原样返回', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2DisplayValue('short text')).toBe('short text')
    wrapper.unmount()
  })

  it('长字符串截断并加省略号', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const long = 'x'.repeat(200)
    const result = vm.memoryV2DisplayValue(long)
    expect(result.length).toBeLessThan(long.length)
    expect(result.endsWith('…')).toBe(true)
    wrapper.unmount()
  })

  it('刚好 160 字符不加省略号', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const exact = 'x'.repeat(160)
    expect(vm.memoryV2DisplayValue(exact)).toBe(exact)
    wrapper.unmount()
  })

  it('null 返回字符串 null（JSON.stringify 行为）', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2DisplayValue(null)).toBe('null')
    wrapper.unmount()
  })
})

describe('SettingsView functions – parseMemoryV2InputValue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('空字符串返回空字符串', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.parseMemoryV2InputValue('')).toBe('')
    expect(vm.parseMemoryV2InputValue('   ')).toBe('')
    wrapper.unmount()
  })

  it('JSON 对象解析为对象', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const result = vm.parseMemoryV2InputValue('{"a":1}')
    expect(result).toEqual({ a: 1 })
    wrapper.unmount()
  })

  it('JSON 数组解析为数组', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const result = vm.parseMemoryV2InputValue('[1,2,3]')
    expect(result).toEqual([1, 2, 3])
    wrapper.unmount()
  })

  it('JSON 字符串解析为字符串', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const result = vm.parseMemoryV2InputValue('"hello"')
    expect(result).toBe('hello')
    wrapper.unmount()
  })

  it('数字字符串解析为数字', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.parseMemoryV2InputValue('42')).toBe(42)
    expect(vm.parseMemoryV2InputValue('-3.14')).toBe(-3.14)
    wrapper.unmount()
  })

  it('true/false/null 解析为对应类型', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.parseMemoryV2InputValue('true')).toBe(true)
    expect(vm.parseMemoryV2InputValue('false')).toBe(false)
    expect(vm.parseMemoryV2InputValue('null')).toBe(null)
    wrapper.unmount()
  })

  it('无效 JSON 返回原字符串', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.parseMemoryV2InputValue('{"invalid"')).toBe('{"invalid"')
    wrapper.unmount()
  })

  it('普通文本返回原字符串', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.parseMemoryV2InputValue('hello world')).toBe('hello world')
    wrapper.unmount()
  })
})

describe('SettingsView functions – memoryV2Time', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('空值返回空字符串', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2Time('')).toBe('')
    expect(vm.memoryV2Time(null)).toBe('')
    expect(vm.memoryV2Time(undefined)).toBe('')
    wrapper.unmount()
  })

  it('有效日期返回格式化字符串', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const result = vm.memoryV2Time('2026-06-25T10:30:00Z')
    expect(result).toBeTruthy()
    expect(typeof result).toBe('string')
    wrapper.unmount()
  })

  it('无效日期返回原字符串', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2Time('not-a-date')).toBe('not-a-date')
    wrapper.unmount()
  })
})

describe('SettingsView functions – canEditMemoryV2', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('pending 状态可编辑', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.canEditMemoryV2({ status: 'pending' })).toBe(true)
    wrapper.unmount()
  })

  it('active 状态可编辑', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.canEditMemoryV2({ status: 'active' })).toBe(true)
    wrapper.unmount()
  })

  it('rejected 状态不可编辑', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.canEditMemoryV2({ status: 'rejected' })).toBe(false)
    wrapper.unmount()
  })

  it('deleted 状态不可编辑', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.canEditMemoryV2({ status: 'deleted' })).toBe(false)
    wrapper.unmount()
  })
})

describe('SettingsView functions – memoryV2FoldMeta computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('初始状态返回 0 计数', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2FoldMeta).toContain('待确认 0')
    expect(vm.memoryV2FoldMeta).toContain('已确认 0')
    wrapper.unmount()
  })

  it('summary 变化后更新计数', async () => {
    mockMemoryV2List.mockResolvedValue({
      success: true,
      memories: [],
      summary: { total: 5, by_status: { pending: 2, active: 3 }, by_type: {} },
      planner_context: '',
    })
    mockMemoryV2Summary.mockResolvedValue({
      success: true,
      summary: { total: 5, by_status: { pending: 2, active: 3 }, by_type: {} },
      planner_context: '',
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.memoryV2FoldMeta).toContain('待确认 2')
    expect(vm.memoryV2FoldMeta).toContain('已确认 3')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * memoryV2 CRUD 操作
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView functions – loadMemoryV2', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('成功加载记忆列表', async () => {
    const records = [{ memory_id: 'm1', memory_type: 'preference', key: 'k1', value: 'v1', status: 'active' }]
    mockMemoryV2List.mockResolvedValue({ success: true, memories: records, summary: { total: 1, by_status: { active: 1 }, by_type: {} }, planner_context: 'ctx' })
    mockMemoryV2Summary.mockResolvedValue({ success: true, summary: { total: 1, by_status: { active: 1 }, by_type: {} }, planner_context: 'ctx' })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    await vm.loadMemoryV2()
    expect(vm.memoryV2Records.length).toBe(1)
    expect(vm.memoryV2PlannerContext).toBe('ctx')
    expect(vm.memoryV2Loading).toBe(false)
    wrapper.unmount()
  })

  it('list 返回 success:false 时设置错误', async () => {
    mockMemoryV2List.mockResolvedValue({ success: false, message: '加载失败' })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.loadMemoryV2()
    expect(vm.memoryV2Error).toContain('加载失败')
    expect(vm.memoryV2Records).toEqual([])
    wrapper.unmount()
  })

  it('summary 返回 success:false 时设置错误', async () => {
    mockMemoryV2List.mockResolvedValue({ success: true, memories: [], summary: { total: 0, by_status: {}, by_type: {} } })
    mockMemoryV2Summary.mockResolvedValue({ success: false, message: '摘要失败' })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.loadMemoryV2()
    expect(vm.memoryV2Error).toContain('摘要失败')
    wrapper.unmount()
  })

  it('API 抛异常时设置错误并清空列表', async () => {
    mockMemoryV2List.mockRejectedValue(new Error('网络错误'))
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.loadMemoryV2()
    expect(vm.memoryV2Error).toContain('网络错误')
    expect(vm.memoryV2Records).toEqual([])
    expect(vm.memoryV2PlannerContext).toBe('')
    expect(vm.memoryV2Loading).toBe(false)
    wrapper.unmount()
  })

  it('list 返回非数组时使用空数组', async () => {
    mockMemoryV2List.mockResolvedValue({ success: true, memories: 'not-array' as any, summary: { total: 0, by_status: {}, by_type: {} } })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.loadMemoryV2()
    expect(vm.memoryV2Records).toEqual([])
    wrapper.unmount()
  })
})

describe('SettingsView functions – createMemoryV2Candidate', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('键或值为空时提示', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.memoryV2Draft.key = ''
    vm.memoryV2Draft.value = 'val'
    await vm.createMemoryV2Candidate()
    expect(mockAppAlert).toHaveBeenCalledWith('请填写记忆键和值')
    expect(mockMemoryV2CreateCandidate).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('成功创建候选记忆', async () => {
    mockMemoryV2CreateCandidate.mockResolvedValue({ success: true })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.memoryV2Draft.key = 'testKey'
    vm.memoryV2Draft.value = 'testValue'
    await vm.createMemoryV2Candidate()
    expect(mockMemoryV2CreateCandidate).toHaveBeenCalled()
    expect(vm.memoryV2Draft.key).toBe('')
    expect(vm.memoryV2Draft.value).toBe('')
    wrapper.unmount()
  })

  it('创建返回 success:false 时设置错误', async () => {
    mockMemoryV2CreateCandidate.mockResolvedValue({ success: false, message: '创建失败' })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.memoryV2Draft.key = 'testKey'
    vm.memoryV2Draft.value = 'testValue'
    await vm.createMemoryV2Candidate()
    expect(vm.memoryV2Error).toContain('创建失败')
    wrapper.unmount()
  })

  it('创建抛异常时设置错误', async () => {
    mockMemoryV2CreateCandidate.mockRejectedValue(new Error('网络错误'))
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.memoryV2Draft.key = 'testKey'
    vm.memoryV2Draft.value = 'testValue'
    await vm.createMemoryV2Candidate()
    expect(vm.memoryV2Error).toContain('网络错误')
    expect(vm.memoryV2Creating).toBe(false)
    wrapper.unmount()
  })
})

describe('SettingsView functions – confirmMemoryV2', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('成功确认记忆', async () => {
    mockMemoryV2Confirm.mockResolvedValue({ success: true })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const record = { memory_id: 'm1', key: 'k1', value: 'v1', status: 'pending' }
    await vm.confirmMemoryV2(record)
    expect(mockMemoryV2Confirm).toHaveBeenCalledWith('m1', expect.any(String))
    expect(vm.memoryV2BusyId).toBe('')
    wrapper.unmount()
  })

  it('确认返回 success:false 时设置错误', async () => {
    mockMemoryV2Confirm.mockResolvedValue({ success: false, message: '确认失败' })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.confirmMemoryV2({ memory_id: 'm1', key: 'k', value: 'v', status: 'pending' })
    expect(vm.memoryV2Error).toContain('确认失败')
    expect(vm.memoryV2BusyId).toBe('')
    wrapper.unmount()
  })

  it('确认抛异常时设置错误', async () => {
    mockMemoryV2Confirm.mockRejectedValue(new Error('网络错误'))
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.confirmMemoryV2({ memory_id: 'm1', key: 'k', value: 'v', status: 'pending' })
    expect(vm.memoryV2Error).toContain('网络错误')
    expect(vm.memoryV2BusyId).toBe('')
    wrapper.unmount()
  })
})

describe('SettingsView functions – rejectMemoryV2', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('用户取消确认时不执行拒绝', async () => {
    mockAppConfirm.mockResolvedValue(false)
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.rejectMemoryV2({ memory_id: 'm1', key: 'k', value: 'v', status: 'pending' })
    expect(mockMemoryV2Reject).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('成功拒绝记忆', async () => {
    mockAppConfirm.mockResolvedValue(true)
    mockMemoryV2Reject.mockResolvedValue({ success: true })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.rejectMemoryV2({ memory_id: 'm1', key: 'k', value: 'v', status: 'pending' })
    expect(mockMemoryV2Reject).toHaveBeenCalled()
    expect(vm.memoryV2BusyId).toBe('')
    wrapper.unmount()
  })

  it('拒绝返回 success:false 时设置错误', async () => {
    mockAppConfirm.mockResolvedValue(true)
    mockMemoryV2Reject.mockResolvedValue({ success: false, message: '拒绝失败' })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.rejectMemoryV2({ memory_id: 'm1', key: 'k', value: 'v', status: 'pending' })
    expect(vm.memoryV2Error).toContain('拒绝失败')
    wrapper.unmount()
  })

  it('拒绝抛异常时设置错误', async () => {
    mockAppConfirm.mockResolvedValue(true)
    mockMemoryV2Reject.mockRejectedValue(new Error('网络错误'))
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.rejectMemoryV2({ memory_id: 'm1', key: 'k', value: 'v', status: 'pending' })
    expect(vm.memoryV2Error).toContain('网络错误')
    expect(vm.memoryV2BusyId).toBe('')
    wrapper.unmount()
  })
})

describe('SettingsView functions – startMemoryV2Edit / cancelMemoryV2Edit', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('startMemoryV2Edit 设置编辑状态', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const record = { memory_id: 'm1', key: 'testKey', value: { a: 1 }, status: 'active' }
    vm.startMemoryV2Edit(record)
    expect(vm.memoryV2Edit.memoryId).toBe('m1')
    expect(vm.memoryV2Edit.key).toBe('testKey')
    expect(vm.memoryV2Edit.value).toContain('"a": 1')
    wrapper.unmount()
  })

  it('startMemoryV2Edit 处理空 key', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.startMemoryV2Edit({ memory_id: 'm1', key: null, value: 'v', status: 'active' })
    expect(vm.memoryV2Edit.key).toBe('')
    wrapper.unmount()
  })

  it('cancelMemoryV2Edit 清空编辑状态', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.memoryV2Edit.memoryId = 'm1'
    vm.memoryV2Edit.key = 'k'
    vm.memoryV2Edit.value = 'v'
    vm.cancelMemoryV2Edit()
    expect(vm.memoryV2Edit.memoryId).toBe('')
    expect(vm.memoryV2Edit.key).toBe('')
    expect(vm.memoryV2Edit.value).toBe('')
    wrapper.unmount()
  })
})

describe('SettingsView functions – saveMemoryV2Edit', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('key 为空时提示', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.memoryV2Edit.key = '   '
    await vm.saveMemoryV2Edit({ memory_id: 'm1', key: 'k', value: 'v', status: 'active' })
    expect(mockAppAlert).toHaveBeenCalledWith('请填写记忆键')
    expect(mockMemoryV2Correct).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('成功保存修正', async () => {
    mockMemoryV2Correct.mockResolvedValue({ success: true })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.memoryV2Edit.key = 'newKey'
    vm.memoryV2Edit.value = 'newValue'
    await vm.saveMemoryV2Edit({ memory_id: 'm1', key: 'k', value: 'v', status: 'active' })
    expect(mockMemoryV2Correct).toHaveBeenCalled()
    expect(vm.memoryV2Edit.memoryId).toBe('')
    expect(vm.memoryV2BusyId).toBe('')
    wrapper.unmount()
  })

  it('修正返回 success:false 时设置错误', async () => {
    mockMemoryV2Correct.mockResolvedValue({ success: false, message: '修正失败' })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.memoryV2Edit.key = 'newKey'
    vm.memoryV2Edit.value = 'newValue'
    await vm.saveMemoryV2Edit({ memory_id: 'm1', key: 'k', value: 'v', status: 'active' })
    expect(vm.memoryV2Error).toContain('修正失败')
    wrapper.unmount()
  })

  it('修正抛异常时设置错误', async () => {
    mockMemoryV2Correct.mockRejectedValue(new Error('网络错误'))
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.memoryV2Edit.key = 'newKey'
    vm.memoryV2Edit.value = 'newValue'
    await vm.saveMemoryV2Edit({ memory_id: 'm1', key: 'k', value: 'v', status: 'active' })
    expect(vm.memoryV2Error).toContain('网络错误')
    expect(vm.memoryV2BusyId).toBe('')
    wrapper.unmount()
  })
})

describe('SettingsView functions – deleteMemoryV2', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('用户取消确认时不执行删除', async () => {
    mockAppConfirm.mockResolvedValue(false)
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.deleteMemoryV2({ memory_id: 'm1', key: 'k', value: 'v', status: 'active' })
    expect(mockMemoryV2Remove).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('成功删除记忆', async () => {
    mockAppConfirm.mockResolvedValue(true)
    mockMemoryV2Remove.mockResolvedValue({ success: true })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.deleteMemoryV2({ memory_id: 'm1', key: 'k', value: 'v', status: 'active' })
    expect(mockMemoryV2Remove).toHaveBeenCalled()
    expect(vm.memoryV2BusyId).toBe('')
    wrapper.unmount()
  })

  it('删除返回 success:false 时设置错误', async () => {
    mockAppConfirm.mockResolvedValue(true)
    mockMemoryV2Remove.mockResolvedValue({ success: false, message: '删除失败' })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.deleteMemoryV2({ memory_id: 'm1', key: 'k', value: 'v', status: 'active' })
    expect(vm.memoryV2Error).toContain('删除失败')
    wrapper.unmount()
  })

  it('删除抛异常时设置错误', async () => {
    mockAppConfirm.mockResolvedValue(true)
    mockMemoryV2Remove.mockRejectedValue(new Error('网络错误'))
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.deleteMemoryV2({ memory_id: 'm1', key: 'k', value: 'v', status: 'active' })
    expect(vm.memoryV2Error).toContain('网络错误')
    expect(vm.memoryV2BusyId).toBe('')
    wrapper.unmount()
  })

  it('删除当前编辑中的记忆时取消编辑', async () => {
    mockAppConfirm.mockResolvedValue(true)
    mockMemoryV2Remove.mockResolvedValue({ success: true })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.memoryV2Edit.memoryId = 'm1'
    vm.memoryV2Edit.key = 'k'
    vm.memoryV2Edit.value = 'v'
    await vm.deleteMemoryV2({ memory_id: 'm1', key: 'k', value: 'v', status: 'active' })
    expect(vm.memoryV2Edit.memoryId).toBe('')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * persy (拟人 Persy) 系列
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView functions – persyFoldMeta computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('无 profile 时返回待确认 0', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.persyFoldMeta).toContain('待确认 0')
    expect(vm.persyFoldMeta).toContain('已确认 0')
    wrapper.unmount()
  })

  it('有 profile 时返回 identity 与互动数', async () => {
    mockButlerProfileGet.mockResolvedValue({
      success: true,
      profile: {
        user_id: 1,
        identity_primary: '助手',
        identity_composite: '复合身份',
        four_axes: { warmth: 50, verbosity: 50, proactiveness: 50, structuredness: 50 },
        mbti_type: 'INTJ',
        mbti_confidence: 0.8,
        interaction_count: 42,
        last_inferred_at: null,
      },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.persyFoldMeta).toContain('复合身份')
    expect(vm.persyFoldMeta).toContain('互动 42')
    wrapper.unmount()
  })

  it('profile 仅有 identity_primary 时使用 primary', async () => {
    mockButlerProfileGet.mockResolvedValue({
      success: true,
      profile: {
        user_id: 1,
        identity_primary: '主身份',
        identity_composite: '',
        four_axes: { warmth: 50, verbosity: 50, proactiveness: 50, structuredness: 50 },
        mbti_type: 'INTJ',
        mbti_confidence: 0.8,
        interaction_count: 5,
        last_inferred_at: null,
      } as any,
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    const vm = wrapper.vm as any
    expect(vm.persyFoldMeta).toContain('主身份')
    wrapper.unmount()
  })
})

describe('SettingsView functions – loadPersyProfile', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('成功加载 profile', async () => {
    const profile = { user_id: 1, identity_primary: '助手', identity_composite: '', four_axes: { warmth: 50, verbosity: 50, proactiveness: 50, structuredness: 50 }, mbti_type: 'INTJ', mbti_confidence: 0.8, interaction_count: 0, last_inferred_at: null }
    mockButlerProfileGet.mockResolvedValue({ success: true, profile })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.loadPersyProfile()
    expect(vm.persyProfile).toEqual(profile)
    expect(vm.persyLoading).toBe(false)
    wrapper.unmount()
  })

  it('返回 success:false 时清空 profile', async () => {
    mockButlerProfileGet.mockResolvedValue({ success: false, message: '加载失败' })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.loadPersyProfile()
    expect(vm.persyProfile).toBeNull()
    expect(vm.persyLoading).toBe(false)
    wrapper.unmount()
  })

  it('API 抛异常时清空 profile', async () => {
    mockButlerProfileGet.mockRejectedValue(new Error('网络错误'))
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.loadPersyProfile()
    expect(vm.persyProfile).toBeNull()
    expect(vm.persyLoading).toBe(false)
    wrapper.unmount()
  })
})

describe('SettingsView functions – runPersyInfer', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('成功推断并更新 profile', async () => {
    const profile = { user_id: 1, identity_primary: '新身份', identity_composite: '', four_axes: { warmth: 50, verbosity: 50, proactiveness: 50, structuredness: 50 }, mbti_type: 'INTJ', mbti_confidence: 0.8, interaction_count: 1, last_inferred_at: null }
    mockButlerProfileInfer.mockResolvedValue({
      success: true,
      profile,
      inference: { mbti_type: 'INTJ', identity_changed: true, confidence: 0.9, reasons: ['原因1', '原因2'] },
    })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.runPersyInfer()
    expect(vm.persyProfile).toEqual(profile)
    expect(vm.persyLastReason).toBe('原因2')
    expect(vm.persyInferring).toBe(false)
    wrapper.unmount()
  })

  it('返回 success:false 时设置错误原因', async () => {
    mockButlerProfileInfer.mockResolvedValue({ success: false, message: '推断失败' })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.runPersyInfer()
    expect(vm.persyLastReason).toContain('推断失败')
    expect(vm.persyInferring).toBe(false)
    wrapper.unmount()
  })

  it('API 抛异常时设置错误原因', async () => {
    mockButlerProfileInfer.mockRejectedValue(new Error('网络错误'))
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.runPersyInfer()
    expect(vm.persyLastReason).toContain('网络错误')
    expect(vm.persyInferring).toBe(false)
    wrapper.unmount()
  })

  it('无 reasons 时清空 lastReason（函数开头会重置）', async () => {
    mockButlerProfileInfer.mockResolvedValue({
      success: true,
      profile: null,
      inference: { mbti_type: 'INTJ', identity_changed: false, confidence: 0.5, reasons: [] },
    })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.persyLastReason = '旧原因'
    await vm.runPersyInfer()
    // 函数开头会执行 persyLastReason.value = ''，无 reasons 时不会重新赋值
    expect(vm.persyLastReason).toBe('')
    wrapper.unmount()
  })
})

describe('SettingsView functions – persyUserId computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('无 user 时返回 1', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.persyUserId).toBe(1)
    wrapper.unmount()
  })

  it('user.id 为有效数字时返回该数字', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValue({
      success: true,
      data: { user: { id: 42, username: 'test', display_name: 'Test', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.persyUserId).toBe(42)
    wrapper.unmount()
  })

  it('user.id 为无效值时返回 1', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValue({
      success: true,
      data: { user: { id: 'invalid', username: 'test', display_name: 'Test', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.persyUserId).toBe(1)
    wrapper.unmount()
  })

  it('user.id 为负数时返回 1', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValue({
      success: true,
      data: { user: { id: -5, username: 'test', display_name: 'Test', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.persyUserId).toBe(1)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * retryModRoutesLoad / onActiveModChange / onUninstallMod
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView functions – retryModRoutesLoad', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('refresh 成功且有 loadError 时提示错误', async () => {
    mockModsStore.refresh.mockResolvedValue(undefined)
    mockModsStore.loadError = '加载错误'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.retryModRoutesLoad()
    expect(mockAppAlert).toHaveBeenCalledWith('加载错误')
    expect(vm.modRoutesRetrying).toBe(false)
    wrapper.unmount()
  })

  it('refresh 成功且 mods 非空但路由为空时提示', async () => {
    mockModsStore.refresh.mockResolvedValue(undefined)
    mockModsStore.loadError = ''
    mockModsStore.mods = [{ id: 'm1' }]
    mockModsStore.modRoutes = []
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.retryModRoutesLoad()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('仍未获取到路由表'))
    wrapper.unmount()
  })

  it('refresh 成功且路由非空时提示已重新加载', async () => {
    mockModsStore.refresh.mockResolvedValue(undefined)
    mockModsStore.loadError = ''
    mockModsStore.mods = [{ id: 'm1' }]
    mockModsStore.modRoutes = [{ path: '/test' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.retryModRoutesLoad()
    expect(mockAppAlert).toHaveBeenCalledWith('Mod 与路由已重新加载。')
    wrapper.unmount()
  })
})

describe('SettingsView functions – onActiveModChange', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })
  afterEach(() => {
    delete (window as any).location
  })

  it('空 modId 时不执行', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const reloadSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: { reload: reloadSpy, href: '' },
    })
    await vm.onActiveModChange('')
    expect(mockModsStore.setActiveModId).not.toHaveBeenCalled()
    expect(reloadSpy).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('modId 与当前相同时不执行', async () => {
    mockModsStore.activeModId = 'same-mod'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const reloadSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: { reload: reloadSpy, href: '' },
    })
    await vm.onActiveModChange('same-mod')
    expect(mockModsStore.setActiveModId).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('有效 modId 时设置并刷新页面', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const reloadSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: { reload: reloadSpy, href: '' },
    })
    await vm.onActiveModChange('new-mod')
    expect(mockModsStore.setActiveModId).toHaveBeenCalledWith('new-mod')
    expect(reloadSpy).toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('SettingsView functions – onUninstallMod', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })
  afterEach(() => {
    delete (window as any).location
  })

  it('空 modId 时不执行', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('')
    expect(mockAppConfirm).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('受保护 mod 时提示不能卸载', async () => {
    mockIsProtectedClientModId.mockReturnValue(true)
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('protected-mod')
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('受保护'))
    expect(mockAppConfirm).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('用户取消确认时不执行卸载', async () => {
    mockIsProtectedClientModId.mockReturnValue(false)
    mockAppConfirm.mockResolvedValue(false)
    mockModsStore.mods = [{ id: 'm1', name: 'Mod 1' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('m1')
    expect(mockApiDelete).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('卸载成功时刷新页面', async () => {
    mockIsProtectedClientModId.mockReturnValue(false)
    mockAppConfirm.mockResolvedValue(true)
    mockApiDelete.mockResolvedValue({ success: true, message: '已卸载' })
    mockModsStore.mods = [{ id: 'm1', name: 'Mod 1' }]
    const reloadSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: { reload: reloadSpy, href: '' },
    })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('m1')
    expect(mockApiDelete).toHaveBeenCalled()
    expect(reloadSpy).toHaveBeenCalled()
    expect(vm.uninstallingModId).toBe('')
    wrapper.unmount()
  })

  it('卸载返回 success:false 时提示失败', async () => {
    mockIsProtectedClientModId.mockReturnValue(false)
    mockAppConfirm.mockResolvedValue(true)
    mockApiDelete.mockResolvedValue({ success: false, message: '卸载失败' })
    mockModsStore.mods = [{ id: 'm1', name: 'Mod 1' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('m1')
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('卸载失败'))
    expect(vm.uninstallingModId).toBe('')
    wrapper.unmount()
  })

  it('卸载抛 ApiError 时提示错误', async () => {
    const { ApiError } = await import('@/api')
    mockIsProtectedClientModId.mockReturnValue(false)
    mockAppConfirm.mockResolvedValue(true)
    mockApiDelete.mockRejectedValue(new ApiError('API 错误'))
    mockModsStore.mods = [{ id: 'm1', name: 'Mod 1' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('m1')
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('API 错误'))
    expect(vm.uninstallingModId).toBe('')
    wrapper.unmount()
  })

  it('卸载抛普通错误时提示错误', async () => {
    mockIsProtectedClientModId.mockReturnValue(false)
    mockAppConfirm.mockResolvedValue(true)
    mockApiDelete.mockRejectedValue(new Error('网络错误'))
    mockModsStore.mods = [{ id: 'm1', name: 'Mod 1' }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('m1')
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('网络错误'))
    expect(vm.uninstallingModId).toBe('')
    wrapper.unmount()
  })

  it('卸载主扩展包时提示包含 primary 标记', async () => {
    mockIsProtectedClientModId.mockReturnValue(false)
    mockAppConfirm.mockResolvedValue(false)
    mockModsStore.mods = [{ id: 'm1', name: 'Mod 1', primary: true }]
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('m1')
    expect(mockAppConfirm).toHaveBeenCalledWith(expect.stringContaining('主扩展'), expect.anything())
    wrapper.unmount()
  })

  it('卸载当前启用扩展包时提示包含刷新说明', async () => {
    mockIsProtectedClientModId.mockReturnValue(false)
    mockAppConfirm.mockResolvedValue(false)
    mockModsStore.mods = [{ id: 'm1', name: 'Mod 1' }]
    mockModsStore.activeModId = 'm1'
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    await vm.onUninstallMod('m1')
    expect(mockAppConfirm).toHaveBeenCalledWith(expect.stringContaining('当前启用'), expect.anything())
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * syncProfileDraftsFromUser / errorMessage
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView functions – syncProfileDraftsFromUser', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('null user 时清空草稿', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.profileDisplayNameDraft = 'old'
    vm.profileEmailDraft = 'old@test.com'
    vm.syncProfileDraftsFromUser(null)
    expect(vm.profileDisplayNameDraft).toBe('')
    expect(vm.profileEmailDraft).toBe('')
    wrapper.unmount()
  })

  it('有 user 时填充草稿', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.syncProfileDraftsFromUser({ id: 1, username: 'test', display_name: '测试', email: 'test@test.com', role: 'user', is_active: true })
    expect(vm.profileDisplayNameDraft).toBe('测试')
    expect(vm.profileEmailDraft).toBe('test@test.com')
    wrapper.unmount()
  })

  it('user 无 display_name 时使用 username', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.syncProfileDraftsFromUser({ id: 1, username: 'testuser', display_name: '', email: '', role: 'user', is_active: true })
    expect(vm.profileDisplayNameDraft).toBe('testuser')
    wrapper.unmount()
  })

  it('user 无 email 时为空字符串', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.syncProfileDraftsFromUser({ id: 1, username: 'testuser', display_name: 'Test', email: undefined as any, role: 'user', is_active: true })
    expect(vm.profileEmailDraft).toBe('')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * modSettingsFoldMeta / basicSettingsSummary / showModRoutesRetry
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView functions – modSettingsFoldMeta computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('无 mods 时返回 0 个行业包（selectableExtensionMods 为空时仍输出 0）', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    // modSettingsFoldMeta = [host, ext, wf].filter(Boolean).join(' · ') || '管理扩展'
    // 当 host='' (空), ext='0 个行业包' (非空字符串), wf='' (空) → '0 个行业包'
    expect(vm.modSettingsFoldMeta).toBe('0 个行业包')
    wrapper.unmount()
  })

  it('有 host bridge mods 时包含核心计数', async () => {
    mockModsStore.mods = [{ id: 'host-bridge-1', name: 'Bridge1' }]
    mockIsHostBridgeModId.mockReturnValue(true)
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.modSettingsFoldMeta).toContain('核心')
    wrapper.unmount()
  })

  it('有 extension mods 时包含行业包计数', async () => {
    mockModsStore.mods = [{ id: 'ext-1', name: 'Ext1' }]
    mockIsHostBridgeModId.mockReturnValue(false)
    mockIsSelectableExtensionModId.mockReturnValue(true)
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.modSettingsFoldMeta).toContain('行业包')
    wrapper.unmount()
  })
})

describe('SettingsView functions – basicSettingsSummary computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('online 模式返回助手名与在线模式', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.aiMode = 'online'
    vm.assistantName = '小智'
    await nextTick()
    expect(vm.basicSettingsSummary).toContain('小智')
    wrapper.unmount()
  })

  it('offline 模式返回助手名与离线模式', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.aiMode = 'offline'
    vm.assistantName = ''
    await nextTick()
    expect(vm.basicSettingsSummary).toContain('修茈')
    wrapper.unmount()
  })
})

describe('SettingsView functions – showModRoutesRetry computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('有 loadError 时返回 true', async () => {
    mockModsStore.loadError = '加载错误'
    mockModsStore.clientModsUiOff = false
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.showModRoutesRetry).toBe(true)
    wrapper.unmount()
  })

  it('clientModsUiOff 时返回 false', async () => {
    mockModsStore.loadError = '加载错误'
    mockModsStore.clientModsUiOff = true
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.showModRoutesRetry).toBe(false)
    wrapper.unmount()
  })

  it('mods 非空但路由为空时返回 true', async () => {
    mockModsStore.loadError = ''
    mockModsStore.clientModsUiOff = false
    mockModsStore.isLoaded = true
    mockModsStore.mods = [{ id: 'm1' }]
    mockModsStore.modRoutes = []
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.showModRoutesRetry).toBe(true)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * hostBridgeMods / hostBridgeInstalledCount / selectableExtensionMods
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView functions – hostBridgeMods computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('过滤并排序 host bridge mods', async () => {
    mockModsStore.mods = [
      { id: 'host-bridge-2', name: 'Bridge2' },
      { id: 'host-bridge-1', name: 'Bridge1' },
      { id: 'other-mod', name: 'Other' },
    ]
    mockIsHostBridgeModId.mockImplementation((id: string) => id.startsWith('host-bridge'))
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    const mods = vm.hostBridgeMods
    expect(mods.length).toBe(2)
    // expected 在前
    expect(mods[0].id).toBe('host-bridge-1')
    wrapper.unmount()
  })

  it('无 host bridge mods 时返回空数组', async () => {
    mockModsStore.mods = [{ id: 'other-mod', name: 'Other' }]
    mockIsHostBridgeModId.mockReturnValue(false)
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.hostBridgeMods).toEqual([])
    wrapper.unmount()
  })
})

describe('SettingsView functions – hostBridgeInstalledCount / hostBridgeExpectedCount', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('计算已安装的 host bridge 数量', async () => {
    mockModsStore.mods = [
      { id: 'host-bridge-1', name: 'Bridge1' },
      { id: 'host-bridge-2', name: 'Bridge2' },
    ]
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.hostBridgeInstalledCount).toBe(2)
    expect(vm.hostBridgeExpectedCount).toBe(2)
    wrapper.unmount()
  })

  it('部分安装时返回部分计数', async () => {
    mockModsStore.mods = [{ id: 'host-bridge-1', name: 'Bridge1' }]
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.hostBridgeInstalledCount).toBe(1)
    expect(vm.hostBridgeExpectedCount).toBe(2)
    wrapper.unmount()
  })
})

describe('SettingsView functions – selectableExtensionMods / workflowEmployeeMods', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('过滤 selectable extension mods', async () => {
    mockModsStore.mods = [
      { id: 'ext-1', name: 'Ext1' },
      { id: 'ext-2', name: 'Ext2' },
      { id: 'other', name: 'Other' },
    ]
    mockIsSelectableExtensionModId.mockImplementation((id: string) => id.startsWith('ext-'))
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.selectableExtensionMods.length).toBe(2)
    wrapper.unmount()
  })

  it('过滤 workflow employee mods', async () => {
    mockModsStore.mods = [
      { id: 'wf-1', name: 'WF1' },
      { id: 'other', name: 'Other' },
    ]
    mockIsWorkflowEmployeeModId.mockImplementation((id: string) => id.startsWith('wf-'))
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.workflowEmployeeMods.length).toBe(1)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════
 * deliveryBrandName / currentIndustryLabel / systemDisplayName / aboutDisplayLine
 * ══════════════════════════════════════════════════════════════════ */

describe('SettingsView functions – deliveryBrandName computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('无 custom mod 且无 brand 时返回空', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.deliveryBrandName).toBe('')
    wrapper.unmount()
  })

  it('有 account custom mod 时返回 mod name', async () => {
    mockModsStore.mods = [{ id: 'taiyangniao-pro', name: '太阳鸟' }]
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.deliveryBrandName).toBe('太阳鸟')
    wrapper.unmount()
  })

  it('无 custom mod 但有 brand 时返回 brand', async () => {
    mockAccountProfileStore.displayBrand = '企业品牌'
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.deliveryBrandName).toBe('企业品牌')
    wrapper.unmount()
  })
})

describe('SettingsView functions – systemDisplayName computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('有 brand 时返回品牌工作台', async () => {
    mockAccountProfileStore.displayBrand = '企业品牌'
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.systemDisplayName).toContain('企业品牌')
    expect(vm.systemDisplayName).toContain('交付工作台')
    wrapper.unmount()
  })

  it('无 brand 时返回通用宿主', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.systemDisplayName).toBe('XCAGI 通用宿主')
    wrapper.unmount()
  })
})

describe('SettingsView functions – aboutDisplayLine computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('有 brand 时返回完整交付线', async () => {
    mockAccountProfileStore.displayBrand = '企业品牌'
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.aboutDisplayLine).toContain('企业品牌')
    expect(vm.aboutDisplayLine).toContain('交付')
    wrapper.unmount()
  })

  it('无 brand 时返回通用宿主说明', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.aboutDisplayLine).toContain('XCAGI 通用宿主')
    expect(vm.aboutDisplayLine).toContain('能力由 Mod 提供')
    wrapper.unmount()
  })
})

describe('SettingsView functions – selectedSidebarAccent computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('匹配主题时返回对应 accent', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.sidebarThemePreset = 'dark'
    await nextTick()
    expect(vm.selectedSidebarAccent).toBe('#1e293b')
    wrapper.unmount()
  })

  it('未匹配主题时返回默认 accent', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.sidebarThemePreset = 'unknown-theme'
    await nextTick()
    expect(vm.selectedSidebarAccent).toBe('#0f6cbd')
    wrapper.unmount()
  })
})

describe('SettingsView functions – intentPackageEntries computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('返回排序后的意图包列表', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    const entries = vm.intentPackageEntries
    expect(entries.length).toBe(5)
    expect(entries[0].key).toBe('base')
    expect(entries[1].key).toBe('industry')
    expect(entries[2].key).toBe('product')
    expect(entries[3].key).toBe('quantity')
    expect(entries[4].key).toBe('customer')
    wrapper.unmount()
  })

  it('keywords 过滤空值并截断到 12 个', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.intentPackages.base.keywords = ['', '考勤', '   ', '查询']
    await nextTick()
    const baseEntry = vm.intentPackageEntries.find((e: any) => e.key === 'base')
    expect(baseEntry.keywords.length).toBe(2)
    expect(baseEntry.keywords).toContain('考勤')
    wrapper.unmount()
  })
})

describe('SettingsView functions – currentIntentIndustryLabel computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('industryStore 有 name 时返回 name', async () => {
    mockIndustryStore.industries = [{ id: 'mfg', name: '制造业', code: 'MFG' }]
    mockIndustryStore.currentIndustry = { id: 'mfg', name: '制造业' }
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.currentIndustry = 'mfg'
    await nextTick()
    expect(vm.currentIntentIndustryLabel).toBe('制造业')
    wrapper.unmount()
  })

  it('无 name 时回退到 preset', async () => {
    mockGetIndustryPreset.mockReturnValue({ name: '预设行业' })
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.currentIndustry = 'default'
    await nextTick()
    expect(vm.currentIntentIndustryLabel).toBe('预设行业')
    wrapper.unmount()
  })
})

describe('SettingsView functions – installedAccountCustomMod computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('找到 account custom mod 时返回该 mod', async () => {
    mockModsStore.mods = [{ id: 'taiyangniao-pro', name: '太阳鸟' }]
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.installedAccountCustomMod).not.toBeNull()
    expect(vm.installedAccountCustomMod.id).toBe('taiyangniao-pro')
    wrapper.unmount()
  })

  it('未找到 account custom mod 时返回 null', async () => {
    mockModsStore.mods = [{ id: 'other-mod', name: 'Other' }]
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.installedAccountCustomMod).toBeNull()
    wrapper.unmount()
  })
})

describe('SettingsView functions – showModelPaymentBridge computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('非 admin console 且未安装 bridge 时返回 false', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.showModelPaymentBridge).toBe(false)
    wrapper.unmount()
  })

  it('非 admin console 但已安装 bridge 时返回 true', async () => {
    mockModsStore.mods = [{ id: 'xcagi-model-payment-bridge', name: 'Bridge' }]
    const wrapper = await mountSettings()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.showModelPaymentBridge).toBe(true)
    wrapper.unmount()
  })
})

describe('SettingsView functions – isLocalAdmin computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('role 为 admin 时返回 true', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValue({
      success: true,
      data: { user: { id: 1, username: 'admin', display_name: 'Admin', email: '', role: 'admin', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.isLocalAdmin).toBe(true)
    wrapper.unmount()
  })

  it('role 为 superadmin 时返回 true', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValue({
      success: true,
      data: { user: { id: 1, username: 'super', display_name: 'Super', email: '', role: 'superadmin', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.isLocalAdmin).toBe(true)
    wrapper.unmount()
  })

  it('role 为 user 时返回 false', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValue({
      success: true,
      data: { user: { id: 1, username: 'user', display_name: 'User', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.isLocalAdmin).toBe(false)
    wrapper.unmount()
  })
})

describe('SettingsView functions – memoryV2UserId computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetApiMocks()
    resetStores()
  })

  it('无 user 时返回 default', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    expect(vm.memoryV2UserId).toBe('default')
    wrapper.unmount()
  })

  it('有 user.username 时返回 username', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValue({
      success: true,
      data: { user: { id: 1, username: 'testuser', display_name: 'Test', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.memoryV2UserId).toBe('testuser')
    wrapper.unmount()
  })

  it('username 为空时 unwrapUserFromMe 返回 null，memoryV2UserId 回退到 default', async () => {
    // unwrapUserFromMe 要求 username 非空，否则返回 null
    mockAuthApiGetCurrentUser.mockResolvedValue({
      success: true,
      data: { user: { id: 42, username: '', display_name: 'Test', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    // localUser.value 为 null（因 username 为空被 unwrapUserFromMe 拒绝）
    expect(vm.memoryV2UserId).toBe('default')
    wrapper.unmount()
  })

  it('username 为空白时回退到 default', async () => {
    mockAuthApiGetCurrentUser.mockResolvedValue({
      success: true,
      data: { user: { id: 0, username: '   ', display_name: 'Test', email: '', role: 'user', is_active: true }, permissions: [] },
    })
    const wrapper = await mountSettings()
    await nextTick()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.memoryV2UserId).toBe('default')
    wrapper.unmount()
  })
})

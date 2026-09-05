import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { RouterView } from 'vue-router'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { clearDeliverableStatusCache } from '@/utils/platformShellApi'
import { invalidateHostPackCompletionCache } from '@/utils/hostPackOnboardingGate'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { invalidateTenantStorageScopeCache } from '@/utils/tenantStorageScope'

const mocks = vi.hoisted(() => ({
  loggedIn: false,
  validateFailure: null as Error | null,
  rejectBinding: false,
  get: vi.fn(), post: vi.fn(), transport: vi.fn(), alert: vi.fn(),
}))
vi.mock('@/api/core', async (original) => {
  const actual = await original<typeof import('@/api/core')>()
  const api = { ...actual.api, get: mocks.get, post: mocks.post }
  return { ...actual, api, default: api, primeCsrfCookie: vi.fn().mockResolvedValue(undefined) }
})
vi.mock('@/utils/apiBase', async (original) => ({ ...await original<typeof import('@/utils/apiBase')>(), apiFetch: mocks.transport }))
vi.mock('@/api/marketAccount', async (original) => ({
  ...await original<typeof import('@/api/marketAccount')>(), applyMarketTokensAfterFhdLogin: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('@/utils/desktopShell', () => ({ isDesktopShell: () => true }))
vi.mock('@/utils/productSku', () => ({ fetchProductSku: vi.fn().mockResolvedValue('enterprise'), isEnterpriseEdition: (sku: string) => sku === 'enterprise' }))
vi.mock('@/utils/appDialog', () => ({ appAlert: mocks.alert }))
vi.mock('@/composables/useTutorialCatalog', () => ({ useTutorialCatalog: () => ({ buildContext: { value: {} } }) }))
vi.mock('@/api/system', () => ({ systemApi: {
  getIndustries: vi.fn().mockResolvedValue({ success: true, data: { industries: [] } }),
  getCurrentIndustry: vi.fn().mockResolvedValue({ success: true, data: { id: '考勤', name: '考勤' } }),
} }))
vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: () => ({ reloadForTenantScope: vi.fn() }), workflowAiEmployeesStorageKey: () => 'test-workflow-employees',
}))
vi.mock('@/stores/workflowEmployeeSpace', () => ({ useWorkflowEmployeeSpaceStore: () => ({ reloadForTenantScope: vi.fn() }) }))
vi.mock('@/stores/mods', () => ({
  readEntitledModIdsFromAuthPayload: () => [],
  useModsStore: () => ({
    clientModsUiOff: false, mods: [], activeModId: '',
    initialize: vi.fn().mockResolvedValue(undefined), reloadActiveModForTenantScope: vi.fn(),
  }),
}))

// Both routed views, login session handler, account hydration, auth cache and
// router guards are real. Only transport/optional Mod discovery are replaced.
import router from './index'

const returnPath = '/data-sources?tab=files&filter=a%26b'
const loginPayload = { success: true, data: { username: 'cold-start-user', account_kind: 'enterprise', market_is_enterprise: true, market_is_admin: false, tenant_id: 10 } }
let wrapper: VueWrapper | undefined

function respond(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

function button(text: string) {
  const match = wrapper!.findAll('button').find((node) => node.text().includes(text))
  expect(match, `visible button: ${text}`).toBeDefined()
  return match!
}

async function selectFromWelcome() {
  await router.replace({ path: '/onboarding', query: { redirect: returnPath } })
  wrapper = mount(RouterView, { global: { plugins: [router] } })
  await flushPromises()
  expect(wrapper.text()).toContain('认识 XC')
  await button('下一步：行业定型').trigger('click')
  await flushPromises()
  await wrapper.get('[role="option"][aria-selected="false"]').trigger('click')
  expect(wrapper.find('[role="option"][aria-selected="true"]').text()).toContain('涂料')
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  setRuntimeTenantStorageScopeInput(null)
  invalidateTenantStorageScopeCache()
  invalidateEnterpriseSessionCache()
  invalidateHostPackCompletionCache()
  clearDeliverableStatusCache()
  setActivePinia(createPinia())
  mocks.loggedIn = false
  mocks.validateFailure = null
  mocks.rejectBinding = false
  mocks.get.mockImplementation(async (path: string) => {
    if (path === '/api/auth/session/validate') {
      if (mocks.validateFailure) throw mocks.validateFailure
      return { success: mocks.loggedIn, valid: mocks.loggedIn }
    }
    if (path === '/api/auth/oidc/status') return { success: true, data: { enabled: false } }
    return loginPayload
  })
  mocks.post.mockImplementation(async (path: string) => {
    if (path !== '/api/auth/login') throw new Error(`Unexpected POST ${path}`)
    mocks.loggedIn = true
    return loginPayload
  })
  mocks.transport.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === '/api/workspace/prefs') {
      if (init?.method === 'PATCH' && (!mocks.loggedIn || mocks.rejectBinding)) return respond({}, 401)
      return respond({ success: true, owner_id: mocks.loggedIn ? 'tenant:10' : null, data: {} })
    }
    if (url === '/api/platform-shell/onboarding-industries') return respond({ data: {
      owner_id: mocks.loggedIn ? 'tenant:10' : null,
      selected_industry_id: '考勤', open_industry_ids: ['考勤', '涂料'],
      open_packages: [{ industry_id: '考勤', mod_id: 'attendance-industry' }, { industry_id: '涂料', mod_id: 'coating-industry' }],
    } })
    if (url.includes('/api/platform-shell/industry-baseline')) return respond({ data: { baseline_ready: false, missing_required_mod_ids: [] } })
    if (url === '/api/platform-shell/deliverable-status') return respond({ data: { deliverable: false } })
    if (url === '/api/platform-shell/onboarding/seed-demo') return respond({ data: { seeded: true, industry_id: '涂料', customer: { id: 1, name: '演示客户' }, product: { id: 2, name: '演示产品' } } })
    throw new Error(`Unexpected transport ${url}`)
  })
})

afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.unstubAllGlobals() })

it('starts at welcome, offers normal login, and resumes the chosen industry before an explicit bind', async () => {
  await selectFromWelcome()
  await button('下一步：准备业务功能').trigger('click')
  await flushPromises()
  expect(wrapper!.text()).toContain('请先登录')
  expect(wrapper!.text()).not.toContain('登录已过期')
  expect(mocks.alert).not.toHaveBeenCalled()
  expect(mocks.transport.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(0)
  expect(mocks.transport.mock.calls.filter(([url]) => url.endsWith('/seed-demo'))).toHaveLength(0)
  await button('登录并继续设置').trigger('click')
  await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('login'))
  await flushPromises()
  await wrapper!.get('#lv-username').setValue('cold-start-user')
  await wrapper!.get('#lv-password').setValue('synthetic-password')
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
  await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('product-onboarding'))
  await flushPromises()
  expect(router.currentRoute.value.query).toMatchObject({ step: 'industry', industry: '涂料', redirect: returnPath })
  expect(wrapper!.find('[role="option"][aria-selected="true"]').text()).toContain('涂料')
  expect(wrapper!.text()).not.toContain('请先登录')
  expect(mocks.transport.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(0)
  await button('下一步：准备业务功能').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.query.step).toBe('host-pack')
  expect(router.currentRoute.value.query.redirect).toBe(returnPath)
  const patches = mocks.transport.mock.calls.filter(([, init]) => init?.method === 'PATCH')
  expect(patches).toHaveLength(1)
  expect(JSON.parse(patches[0][1].body)).toMatchObject({ selected_industry_id: '涂料', industry_mod_id: 'coating-industry' })
})

it('keeps a retry available when session validation is offline without attempting a binding', async () => {
  await selectFromWelcome()
  mocks.validateFailure = new Error('network offline')
  await button('下一步：准备业务功能').trigger('click')
  await flushPromises()
  expect(mocks.alert).toHaveBeenCalled()
  expect(String(mocks.alert.mock.calls[0][0])).not.toContain('登录已过期')
  expect(mocks.transport.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(0)
  expect(router.currentRoute.value.query.step).toBe('industry')
  expect(button('下一步：准备业务功能').attributes('disabled')).toBeUndefined()
})

it('also offers login when the session disappears between validation and the protected write', async () => {
  await selectFromWelcome()
  const consumeBootstrapSessionHint = vi.fn().mockResolvedValue(true)
  vi.stubGlobal('xcagiDesktop', { consumeBootstrapSessionHint })
  mocks.loggedIn = true
  mocks.rejectBinding = true
  await button('下一步：准备业务功能').trigger('click')
  await flushPromises()
  expect(wrapper!.text()).toContain('请先登录')
  expect(button('登录并继续设置').exists()).toBe(true)
  expect(mocks.alert).not.toHaveBeenCalled()
  expect(router.currentRoute.value.query.step).toBe('industry')
  expect(mocks.transport.mock.calls.filter(([url]) => url.endsWith('/seed-demo'))).toHaveLength(0)
  await button('登录并继续设置').trigger('click')
  await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('login'))
  await flushPromises()
  expect(router.currentRoute.value.name).toBe('login')
  expect(wrapper!.find('#lv-username').exists()).toBe(true)
  expect(consumeBootstrapSessionHint).not.toHaveBeenCalled()
})

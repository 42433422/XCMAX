import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { authApi } from '@/api/auth'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useLoginViewSession } from '@/views/login-view/useLoginViewSession'
import { useLoginViewState } from '@/views/login-view/useLoginViewState'
import { hasRecentEnterpriseSessionHint, invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { invalidateHostPackCompletionCache } from '@/utils/hostPackOnboardingGate'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { invalidateTenantStorageScopeCache } from '@/utils/tenantStorageScope'
import { setPlannerModFacadeEnabled } from '@/constants/plannerMod'
import type { OnboardingIndustryCatalog } from '@/constants/platformShell'

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  get: vi.fn(),
  prefs: vi.fn(),
  catalog: vi.fn(),
  baseline: vi.fn(),
  backgroundRefresh: vi.fn(),
}))

vi.mock('@/api/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/core')>()
  const api = { ...actual.api, get: mocks.get, post: mocks.post }
  return { ...actual, api, default: api, primeCsrfCookie: vi.fn().mockResolvedValue(undefined) }
})
vi.mock('@/utils/apiBase', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/utils/apiBase')>(),
  apiFetch: mocks.prefs,
}))
vi.mock('@/api/marketAccount', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/marketAccount')>(),
  applyMarketTokensAfterFhdLogin: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('@/utils/productSku', () => ({
  fetchProductSku: vi.fn().mockResolvedValue('enterprise'),
  isEnterpriseEdition: (sku: string) => sku === 'enterprise',
}))
vi.mock('@/utils/platformShellApi', () => ({
  fetchOnboardingIndustryCatalog: mocks.catalog,
  fetchIndustryBaseline: mocks.baseline,
  clearDeliverableStatusCache: vi.fn(),
}))
vi.mock('@/utils/desktopShell', () => ({ isDesktopShell: () => true }))
vi.mock('@/utils/desktopSessionRestore', () => ({ refreshDesktopSessionInBackground: mocks.backgroundRefresh }))
vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: () => ({ reloadForTenantScope: vi.fn() }),
  workflowAiEmployeesStorageKey: () => 'test-workflow-employees',
}))
vi.mock('@/stores/workflowEmployeeSpace', () => ({
  useWorkflowEmployeeSpaceStore: () => ({ reloadForTenantScope: vi.fn() }),
}))
vi.mock('@/stores/mods', () => ({
  readEntitledModIdsFromAuthPayload: () => [],
  useModsStore: () => ({
    clientModsUiOff: false, mods: [], activeModId: '',
    initialize: vi.fn().mockResolvedValue(undefined), reloadActiveModForTenantScope: vi.fn(),
  }),
}))
vi.mock('@/views/LoginView.vue', () => ({ default: { template: '<div>Login</div>' } }))
vi.mock('@/views/ProductOnboardingView.vue', () => ({ default: { template: '<div>Onboarding</div>' } }))
vi.mock('@/views/ChatView.vue', () => ({ default: { template: '<div>Chat</div>' } }))

import router from './index'

const loginPayload = {
  success: true,
  data: { username: 'new-enterprise', account_kind: 'enterprise', market_is_enterprise: true, market_is_admin: false, tenant_id: 10 },
}
const modChatPath = '/mod/xcagi-planner-bridge/chat'

function prefsResponse(data = {}, ownerId: string | null = 'tenant:10') {
  return new Response(JSON.stringify({ success: true, owner_id: ownerId, data }), {
    headers: { 'Content-Type': 'application/json' },
  })
}

async function beginNormalLogin() {
  const state = useLoginViewState(router.currentRoute.value)
  state.productSku.value = 'enterprise'
  state.username.value = 'new-enterprise'
  const result = await authApi.login('new-enterprise', 'synthetic-test-password', 'enterprise')
  expect(hasRecentEnterpriseSessionHint()).toBe(true)
  return { complete: () => useLoginViewSession(state, { router }).completeLoginSuccess(result as unknown as Record<string, unknown>) }
}

describe('normal desktop login through the real onboarding router guard', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    setRuntimeTenantStorageScopeInput(null)
    invalidateTenantStorageScopeCache()
    invalidateEnterpriseSessionCache()
    invalidateHostPackCompletionCache()
    setActivePinia(createPinia())
    mocks.post.mockResolvedValue(loginPayload)
    mocks.get.mockResolvedValue(loginPayload)
    mocks.prefs.mockImplementation(async (url: string) => {
      if (url !== '/api/workspace/prefs') throw new Error(`unexpected API ${url}`)
      return prefsResponse()
    })
    mocks.catalog.mockResolvedValue({
      owner_id: 'tenant:10', selected_industry_id: '', enterprise_filter_applied: true,
      open_industry_ids: ['涂料'],
      open_packages: [{ industry_id: '涂料', mod_id: 'coating-industry', product_name: '涂料', selectable: true }],
    } satisfies OnboardingIndustryCatalog)
    mocks.baseline.mockResolvedValue({ baseline_ready: true, missing_required_mod_ids: [] })
    router.addRoute({ path: modChatPath, name: 'mod-planner-chat', component: { template: '<div>Mod chat</div>' }, meta: { mod: true } })
    setPlannerModFacadeEnabled(true)
    await router.replace('/login')
  })

  it('does not let the fresh login session hint skip industry selection on a preinstalled desktop', async () => {
    expect(useAccountProfileStore().loaded).toBe(false)
    const login = await beginNormalLogin()
    await login.complete()
    expect(useAccountProfileStore().loaded).toBe(true)
    expect(mocks.backgroundRefresh).not.toHaveBeenCalled()
    expect(router.currentRoute.value.name).toBe('product-onboarding')
    expect(router.currentRoute.value.query).toMatchObject({ step: 'industry', redirect: modChatPath })
    expect(mocks.catalog).toHaveBeenCalled()
    expect(mocks.prefs).toHaveBeenCalledTimes(2)
  })

  it('awaits delayed profile preference hydration before routing a previously completed customer', async () => {
    let releaseHydration!: (response: Response) => void
    mocks.prefs.mockImplementationOnce(() => new Promise((resolve) => { releaseHydration = resolve }))
    mocks.prefs.mockImplementation(async () => prefsResponse({ product_flow_completed: true }))
    const login = await beginNormalLogin()
    const completing = login.complete()
    await vi.waitFor(() => expect(mocks.prefs).toHaveBeenCalledTimes(1))
    expect(useAccountProfileStore().loaded).toBe(true)
    expect(router.currentRoute.value.name).toBe('login')
    expect(mocks.catalog).not.toHaveBeenCalled()

    releaseHydration(prefsResponse({ product_flow_completed: true }))
    await completing
    expect(router.currentRoute.value.path).toBe(modChatPath)
    expect(mocks.backgroundRefresh).not.toHaveBeenCalled()
  })

  it.each(['no-permission', 'missing-owner', 'owner-mismatch', 'offline'] as const)(
    'keeps normal login usable without an onboarding redirect loop for %s', async (condition) => {
      if (condition === 'no-permission') mocks.catalog.mockResolvedValue({ owner_id: 'tenant:10', open_industry_ids: [], open_packages: [] })
      if (condition === 'missing-owner') mocks.catalog.mockResolvedValue({ owner_id: null, open_industry_ids: ['涂料'], open_packages: [{ industry_id: '涂料' }] })
      if (condition === 'owner-mismatch') mocks.prefs.mockImplementation(async () => prefsResponse({}, 'tenant:20'))
      if (condition === 'offline') mocks.catalog.mockRejectedValue(new Error('offline'))
      const login = await beginNormalLogin()
      await login.complete()
      expect(router.currentRoute.value.path).toBe(modChatPath)
      expect(mocks.backgroundRefresh).not.toHaveBeenCalled()
    },
  )
})

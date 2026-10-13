import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAccountProfileStore } from './accountProfile'
import { refreshTenantScopedClientStores } from '@/utils/refreshTenantScopedClientStores'

vi.mock('@/api/auth', () => ({
  authApi: {
    getCurrentUser: vi.fn().mockResolvedValue({ success: true, data: {} }),
  },
}))

vi.mock('@/utils/authSessionCache', () => ({
  invalidateEnterpriseSessionCache: vi.fn(),
  validateEnterpriseSessionCached: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/utils/productSku', () => ({
  fetchProductSku: vi.fn().mockResolvedValue('generic'),
  isEnterpriseEdition: vi.fn().mockReturnValue(false),
}))

vi.mock('@/utils/refreshTenantScopedClientStores', () => ({
  refreshTenantScopedClientStores: vi.fn().mockResolvedValue(undefined),
}))

const { loadIndustry } = vi.hoisted(() => ({ loadIndustry: vi.fn().mockResolvedValue(undefined) }))
vi.mock('@/stores/industry', () => ({ useIndustryStore: () => ({ loadFromServer: loadIndustry }) }))

vi.mock('@/utils/tenantStorageScopeRuntime', () => ({
  setRuntimeTenantStorageScopeInput: vi.fn(),
}))

describe('useAccountProfileStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('initializes with default state', () => {
    const store = useAccountProfileStore()
    expect(store.accountKind).toBe('enterprise')
    expect(store.companyBrand).toBe('')
    expect(store.marketIsAdmin).toBe(false)
    expect(store.marketIsEnterprise).toBe(false)
    expect(store.tenantId).toBeNull()
    expect(store.tenantName).toBe('')
    expect(store.marketUserId).toBeNull()
    expect(store.localUserId).toBeNull()
    expect(store.impersonatingMarketUserId).toBeNull()
    expect(store.impersonatingUsername).toBe('')
    expect(store.loaded).toBe(false)
  })

  it.each<[string, 'admin' | 'enterprise', boolean, boolean]>([
    ['admin kind + admin flag', 'admin', true, true],
    ['enterprise kind + admin flag', 'enterprise', true, false],
  ])('isAdminAccount with %s', (_label, kind, flag, expected) => {
    const store = useAccountProfileStore()
    store.accountKind = kind
    store.marketIsAdmin = flag
    expect(store.isAdminAccount).toBe(expected)
  })

  it.each<[number | null, boolean]>([
    [5, true],
    [null, false],
  ])('isImpersonating with %s', (value, expected) => {
    const store = useAccountProfileStore()
    store.impersonatingMarketUserId = value
    expect(store.isImpersonating).toBe(expected)
  })

  it.each<[string, string]>([
    ['  Test Brand  ', 'Test Brand'],
    ['   ', ''],
  ])('displayBrand for %j', (raw, expected) => {
    const store = useAccountProfileStore()
    store.companyBrand = raw
    expect(store.displayBrand).toBe(expected)
  })

  it.each<[string, null | undefined]>([
    ['null', null],
    ['undefined', undefined],
  ])('applyFromMeData does nothing with %s', async (_label, value) => {
    const store = useAccountProfileStore()
    await store.applyFromMeData(value)
    expect(store.loaded).toBe(false)
  })

  it('applyFromMeData applies session fields', async () => {
    const store = useAccountProfileStore()
    await store.applyFromMeData({
      account_kind: 'personal',
      company_brand: 'TestCo',
      market_is_admin: true,
      market_is_enterprise: false,
      tenant_id: 10,
      tenant_name: 'Tenant10',
      market_user_id: 20,
      local_user_id: 30,
    })
    expect(store.accountKind).toBe('personal')
    expect(store.companyBrand).toBe('TestCo')
    expect(store.marketIsAdmin).toBe(true)
    expect(store.tenantId).toBe(10)
    expect(store.tenantName).toBe('Tenant10')
    expect(store.marketUserId).toBe(20)
    expect(store.localUserId).toBe(30)
    expect(store.loaded).toBe(true)
  })

  it.each<[string, Record<string, unknown>, string, string]>([
    ['nested data field', { data: { account_kind: 'admin', company_brand: 'AdminCo' } }, 'admin', 'AdminCo'],
    ['raw payload', { account_kind: 'enterprise', company_brand: 'DirectCo' }, 'enterprise', 'DirectCo'],
  ])('applyFromLoginPayload reads %s and keeps the known account scope', async (_label, payload, kind, brand) => {
    const store = useAccountProfileStore()
    await store.applyFromMeData({ tenant_id: 10, permissions: ['tenant.manage_roles'], tenant_name: 'T10' })
    await store.applyFromLoginPayload(payload)
    expect(store.accountKind).toBe(kind)
    expect(store.companyBrand).toBe(brand)
    // 登录响应不含 tenant/权限键：缺失键必须保留已知状态，否则设置页的权限入口会被清掉
    expect(store.tenantId).toBe(10)
    expect(store.permissions).toEqual(['tenant.manage_roles'])
  })

  it('applyFromMeData clears the account scope when the payload says so explicitly', async () => {
    const store = useAccountProfileStore()
    await store.applyFromMeData({ tenant_id: 10, permissions: ['tenant.manage_roles'] })
    await store.applyFromMeData({ tenant_id: null, permissions: [] })
    expect(store.tenantId).toBeNull()
    expect(store.permissions).toEqual([])
  })

  it('applyFromMeData reads local_user_id from nested user object', async () => {
    const store = useAccountProfileStore()
    await store.applyFromMeData({
      account_kind: 'enterprise',
      company_brand: '',
      market_is_admin: false,
      market_is_enterprise: false,
      tenant_id: null,
      market_user_id: null,
      local_user_id: null,
      user: { id: 99 },
    })
    expect(store.localUserId).toBe(99)
  })

  it('applyFromMeData sets impersonating fields', async () => {
    const store = useAccountProfileStore()
    await store.applyFromMeData({
      account_kind: 'enterprise',
      company_brand: '',
      market_is_admin: false,
      market_is_enterprise: false,
      tenant_id: null,
      market_user_id: null,
      local_user_id: null,
      impersonating_market_user_id: 42,
      impersonating_username: 'admin_user',
    })
    expect(store.impersonatingMarketUserId).toBe(42)
    expect(store.impersonatingUsername).toBe('admin_user')
  })

  it('clear resets all state', async () => {
    const store = useAccountProfileStore()
    await store.applyFromMeData({
      account_kind: 'admin',
      company_brand: 'Test',
      market_is_admin: true,
      market_is_enterprise: true,
      tenant_id: 1,
      tenant_name: 'T1',
      market_user_id: 2,
      local_user_id: 3,
    })
    store.clear()
    expect(store.accountKind).toBe('enterprise')
    expect(store.companyBrand).toBe('')
    expect(store.marketIsAdmin).toBe(false)
    expect(store.loaded).toBe(false)
  })

  it.each<[string, Error, boolean]>([
    ['server rejects the session (401)', Object.assign(new Error('Unauthorized'), { status: 401 }), false],
    ['transient network failure', new Error('Network error'), true],
    ['superseded refresh (abort)', Object.assign(new Error('signal is aborted without reason'), { name: 'AbortError' }), true],
  ])('refreshFromServer on %s keeps loaded=%s', async (_label, error, keeps) => {
    const { authApi } = await import('@/api/auth')
    vi.mocked(authApi.getCurrentUser).mockRejectedValueOnce(error)
    const store = useAccountProfileStore()
    store.loaded = true
    await store.refreshFromServer()
    // 会话明确失效才清空；瞬时失败保留最近资料，否则依赖权限的入口（如「角色与权限」）会消失
    expect(store.loaded).toBe(keeps)
  })

  it('waits for tenant preference hydration before refresh resolves', async () => {
    let releaseHydration: (() => void) | undefined
    vi.mocked(refreshTenantScopedClientStores).mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          releaseHydration = resolve
        }),
    )
    const { authApi } = await import('@/api/auth')
    vi.mocked(authApi.getCurrentUser).mockResolvedValueOnce({
      success: true,
      data: { account_kind: 'enterprise', tenant_id: 1, local_user_id: 2 },
    })
    const store = useAccountProfileStore()
    let resolved = false
    const refresh = store.refreshFromServer().then(() => {
      resolved = true
    })

    await vi.waitFor(() => expect(store.loaded).toBe(true))
    expect(resolved).toBe(false)

    releaseHydration?.()
    await refresh
    expect(resolved).toBe(true)
  })
  it.each(['me', 'industry'].flatMap(phase => [401, 403, 'success'].map(outcome => ({ phase, outcome }))))('ignores old background $phase $outcome after a newer login', async ({ phase, outcome }) => {
    const store = useAccountProfileStore()
    await store.applyFromMeData({ tenant_id: 10, permissions: ['old.read'] })
    const { authApi } = await import('@/api/auth')
    let finish!: (value: unknown) => void
    let fail!: (error: unknown) => void
    const pending = () => new Promise<any>((resolve, reject) => { finish = resolve; fail = reject })
    if (phase === 'me') vi.mocked(authApi.getCurrentUser).mockImplementationOnce(pending)
    else {
      vi.mocked(authApi.getCurrentUser).mockResolvedValueOnce({ success: true, data: { tenant_id: 10 } } as any)
      loadIndustry.mockImplementationOnce(pending)
    }
    const refreshing = store.refreshFromServer()
    await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
    await store.applyFromLoginPayload({ tenant_id: 20, company_brand: 'new-account', permissions: ['new.read'] })
    if (outcome === 'success') finish({ success: true, data: { tenant_id: 10, permissions: ['old.read'] } })
    else fail(Object.assign(new Error('old session rejected'), { status: outcome }))
    await refreshing
    expect(store.tenantId).toBe(20)
    expect(store.companyBrand).toBe('new-account')
    expect(store.permissions).toEqual(['new.read'])
    expect(store.workspaceReady).toBe(true)
  })

})

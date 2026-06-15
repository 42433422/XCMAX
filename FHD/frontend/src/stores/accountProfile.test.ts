import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAccountProfileStore } from './accountProfile'

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
  refreshTenantScopedClientStores: vi.fn(),
}))

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

  it('isAdminAccount is true when admin kind and admin flag', () => {
    const store = useAccountProfileStore()
    store.accountKind = 'admin'
    store.marketIsAdmin = true
    expect(store.isAdminAccount).toBe(true)
  })

  it('isAdminAccount is false when not admin kind', () => {
    const store = useAccountProfileStore()
    store.accountKind = 'enterprise'
    store.marketIsAdmin = true
    expect(store.isAdminAccount).toBe(false)
  })

  it('isImpersonating is true when impersonatingMarketUserId is set', () => {
    const store = useAccountProfileStore()
    store.impersonatingMarketUserId = 5
    expect(store.isImpersonating).toBe(true)
  })

  it('isImpersonating is false when impersonatingMarketUserId is null', () => {
    const store = useAccountProfileStore()
    expect(store.isImpersonating).toBe(false)
  })

  it('displayBrand returns trimmed company brand', () => {
    const store = useAccountProfileStore()
    store.companyBrand = '  Test Brand  '
    expect(store.displayBrand).toBe('Test Brand')
  })

  it('displayBrand returns empty string when brand is empty', () => {
    const store = useAccountProfileStore()
    store.companyBrand = '   '
    expect(store.displayBrand).toBe('')
  })

  it('applyFromMeData does nothing with null', () => {
    const store = useAccountProfileStore()
    store.applyFromMeData(null)
    expect(store.loaded).toBe(false)
  })

  it('applyFromMeData does nothing with undefined', () => {
    const store = useAccountProfileStore()
    store.applyFromMeData(undefined)
    expect(store.loaded).toBe(false)
  })

  it('applyFromMeData applies session fields', () => {
    const store = useAccountProfileStore()
    store.applyFromMeData({
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

  it('applyFromLoginPayload extracts data from nested data field', () => {
    const store = useAccountProfileStore()
    store.applyFromLoginPayload({
      data: {
        account_kind: 'admin',
        company_brand: 'AdminCo',
        market_is_admin: true,
        market_is_enterprise: true,
        tenant_id: 1,
        tenant_name: 'AdminTenant',
        market_user_id: 2,
        local_user_id: 3,
      },
    })
    expect(store.accountKind).toBe('admin')
    expect(store.companyBrand).toBe('AdminCo')
  })

  it('applyFromLoginPayload uses raw when data is not object', () => {
    const store = useAccountProfileStore()
    store.applyFromLoginPayload({
      account_kind: 'enterprise',
      company_brand: 'DirectCo',
      market_is_admin: false,
      market_is_enterprise: true,
      tenant_id: 5,
      tenant_name: 'DirectTenant',
      market_user_id: 6,
      local_user_id: 7,
    })
    expect(store.accountKind).toBe('enterprise')
    expect(store.companyBrand).toBe('DirectCo')
  })

  it('applyFromMeData reads local_user_id from nested user object', () => {
    const store = useAccountProfileStore()
    store.applyFromMeData({
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

  it('applyFromMeData sets impersonating fields', () => {
    const store = useAccountProfileStore()
    store.applyFromMeData({
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

  it('clear resets all state', () => {
    const store = useAccountProfileStore()
    store.applyFromMeData({
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

  it('refreshFromServer clears on failure', async () => {
    const { authApi } = await import('@/api/auth')
    vi.mocked(authApi.getCurrentUser).mockRejectedValueOnce(new Error('Network error'))
    const store = useAccountProfileStore()
    store.loaded = true
    await store.refreshFromServer()
    expect(store.loaded).toBe(false)
  })
})

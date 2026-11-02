import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { invalidateEnterpriseSessionCache, markEnterpriseSessionValid } from '@/utils/authSessionCache'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import { useAccountProfileStore } from './accountProfile'

const boundary = vi.hoisted(() => {
  function request() {
    let resolve!: () => void, reject!: (error: unknown) => void
    const promise = new Promise<void>((ok, fail) => { resolve = ok; reject = fail })
    return { promise, resolve, reject }
  }
  return {
    request,
    preferences: [] as ReturnType<typeof request>[],
    industries: [] as ReturnType<typeof request>[],
    getCurrentUser: vi.fn(),
    validateSession: vi.fn(),
    enterprise: false,
  }
})
vi.mock('@/api/auth', () => ({ authApi: { getCurrentUser: boundary.getCurrentUser, validateSession: boundary.validateSession } }))
vi.mock('@/utils/productSku', () => ({ fetchProductSku: vi.fn(async () => boundary.enterprise ? 'enterprise' : 'generic'), isEnterpriseEdition: () => boundary.enterprise }))
vi.mock('@/utils/refreshTenantScopedClientStores', async () => {
  const { updateProductReadAccountScope } = await import('@/utils/productReadAccountScope')
  return { refreshTenantScopedClientStores: vi.fn((input) => {
    // Match the production contract: the account epoch changes synchronously,
    // before the returned preference-hydration promise can settle.
    updateProductReadAccountScope(input)
    const read = boundary.request()
    boundary.preferences.push(read)
    return read.promise
  }) }
})
vi.mock('@/stores/industry', () => ({ useIndustryStore: () => ({ loadFromServer: vi.fn(() => {
  const read = boundary.request()
  boundary.industries.push(read)
  return read.promise
}) }) }))
vi.mock('@/utils/tenantStorageScopeRuntime', () => ({ setRuntimeTenantStorageScopeInput: vi.fn(), getRuntimeTenantStorageScopeInput: () => null }))

function account(id: number, brand = `account-${id}`) {
  return { account_kind: 'enterprise', tenant_id: id, market_user_id: id * 10,
    local_user_id: id * 100, company_brand: brand }
}
function observe(promise: Promise<void>) {
  const result = { settled: false, error: undefined as unknown }
  const done = promise.then(() => { result.settled = true }, error => { result.settled = true; result.error = error })
  return { result, done }
}
async function preferencesReady(index: number) {
  boundary.preferences[index].resolve()
  await flushPromises()
}
async function ready(store: ReturnType<typeof useAccountProfileStore>) {
  const initial = store.applyFromMeData(account(1))
  await preferencesReady(0)
  boundary.industries[0].resolve()
  await initial
}
beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  boundary.enterprise = false
  boundary.getCurrentUser.mockReset()
  boundary.validateSession.mockReset()
  boundary.preferences.length = 0
  boundary.industries.length = 0
  invalidateEnterpriseSessionCache()
  updateProductReadAccountScope({ tenantId: -1, accountKind: 'enterprise' })
})
afterEach(async () => {
  // Finish synthetic reads without leaving timers, network requests or rejected tasks behind.
  for (const read of boundary.preferences) read.resolve()
  await flushPromises()
  for (const read of boundary.industries) read.resolve()
  await flushPromises()
})

describe('account workspace hydration ownership', () => {
  it.each(['me', 'login'] as const)('immediately closes prior readiness when new %s hydration starts', async source => {
    const store = useAccountProfileStore()
    await ready(store)
    expect(store.workspaceReady).toBe(true)
    const next = observe(source === 'me' ? store.applyFromMeData(account(1)) : store.applyFromLoginPayload({ data: account(1) }))
    expect(store.workspaceReady).toBe(false)
    await preferencesReady(1)
    expect(store.workspaceReady).toBe(false)
    boundary.industries[1].resolve()
    await next.done
    expect(next.result.error).toBeUndefined()
    expect(store.workspaceReady).toBe(true)
  })

  it('keeps a superseded refresh waiting for the same-account hydration when the older me response arrives', async () => {
    const store = useAccountProfileStore()
    await ready(store)
    let respond!: (value: unknown) => void
    boundary.getCurrentUser.mockReturnValue(new Promise(resolve => { respond = resolve }))
    const refresh = observe(store.refreshFromServer())
    await flushPromises()
    expect(boundary.getCurrentUser).toHaveBeenCalledOnce()
    const latest = observe(store.applyFromMeData(account(1, 'latest-hydration')))
    expect(store.workspaceReady).toBe(false)
    respond({ success: true, data: account(1, 'older-me-response') })
    await flushPromises()
    expect(refresh.result.settled).toBe(false)
    expect(store.workspaceReady).toBe(false)
    await preferencesReady(1)
    boundary.industries[1].resolve()
    await Promise.all([refresh.done, latest.done])
    expect(refresh.result.error).toBeUndefined()
    expect(store.workspaceReady).toBe(true)
    expect(store.companyBrand).toBe('latest-hydration')
  })

  it('keeps a superseded enterprise refresh waiting for hydration after older validation succeeds', async () => {
    const store = useAccountProfileStore()
    await ready(store)
    boundary.enterprise = true
    let validate!: (value: unknown) => void
    boundary.validateSession.mockReturnValue(new Promise(resolve => { validate = resolve }))
    const refresh = observe(store.refreshFromServer())
    await flushPromises()
    expect(boundary.validateSession).toHaveBeenCalledOnce()
    const latest = observe(store.applyFromMeData(account(1, 'latest-hydration')))
    validate({ success: true, data: { valid: true } })
    await flushPromises()
    expect(refresh.result.settled).toBe(false)
    expect(store.workspaceReady).toBe(false)
    await preferencesReady(1)
    boundary.industries[1].resolve()
    await Promise.all([refresh.done, latest.done])
    expect(refresh.result.error).toBeUndefined()
    expect(store.workspaceReady).toBe(true)
    expect(boundary.getCurrentUser).not.toHaveBeenCalled()
  })

  it.each(['network', 401, 403] as const)('keeps refresh resolution semantics when latest same-owner hydration fails with %s', async failure => {
    const store = useAccountProfileStore()
    await ready(store)
    let respond!: (value: unknown) => void
    boundary.getCurrentUser.mockReturnValue(new Promise(resolve => { respond = resolve }))
    const refresh = observe(store.refreshFromServer())
    await flushPromises()
    const latest = observe(store.applyFromMeData(account(1, 'latest-identity')))
    respond({ success: true, data: account(1, 'older-response') })
    await flushPromises()
    expect(refresh.result.settled).toBe(false)
    await preferencesReady(1)
    const error = failure === 'network' ? new Error('latest network unavailable')
      : Object.assign(new Error('latest session rejected'), { status: failure })
    boundary.industries[1].reject(error)
    await Promise.all([refresh.done, latest.done])
    expect(latest.result.error).toBe(error)
    expect(refresh.result.error).toBeUndefined()
    expect(store.workspaceReady).toBe(false)
    if (failure === 'network') {
      expect(store.sessionCheckUnavailable).toBe(true)
      expect(store.loaded).toBe(true)
      expect(store.tenantId).toBe(1)
      expect(store.localUserId).toBe(100)
      expect(store.companyBrand).toBe('latest-identity')
    } else {
      expect(store.sessionCheckUnavailable).toBe(false)
      expect(store.loaded).toBe(false)
      expect(store.tenantId).toBeNull()
      expect(store.localUserId).toBeNull()
      expect(store.companyBrand).toBe('')
    }
  })

  it('does not clear or mark unavailable a successful latest owner when an older refresh is rejected', async () => {
    const store = useAccountProfileStore()
    await ready(store)
    let rejectOld!: (error: unknown) => void
    boundary.getCurrentUser.mockReturnValue(new Promise((_resolve, reject) => { rejectOld = reject }))
    const refresh = observe(store.refreshFromServer())
    await flushPromises()
    const latest = observe(store.applyFromMeData(account(1, 'latest-success')))
    await preferencesReady(1)
    boundary.industries[1].resolve()
    await latest.done
    expect(store.workspaceReady).toBe(true)
    rejectOld(Object.assign(new Error('old unauthorized response'), { status: 401 }))
    await refresh.done
    expect(refresh.result.error).toBeUndefined()
    expect(store.sessionCheckUnavailable).toBe(false)
    expect(store.loaded).toBe(true)
    expect(store.workspaceReady).toBe(true)
    expect(store.companyBrand).toBe('latest-success')
  })

  it('accepts the newest same-account hydration when industry responses finish in reverse order', async () => {
    const store = useAccountProfileStore()
    const old = observe(store.applyFromMeData(account(1, 'old')))
    await preferencesReady(0)
    const latest = observe(store.applyFromMeData(account(1, 'latest')))
    await preferencesReady(1)
    boundary.industries[1].resolve()
    await latest.done
    expect(store.workspaceReady).toBe(true)
    boundary.industries[0].resolve()
    await old.done
    expect(old.result.error).toBeUndefined()
    expect(store.companyBrand).toBe('latest')
    expect(store.workspaceReady).toBe(true)
  })

  it.each(['success', 'error'] as const)('keeps an old same-account %s caller waiting for the latest pending hydration', async outcome => {
    const store = useAccountProfileStore()
    const old = observe(store.applyFromMeData(account(1)))
    await preferencesReady(0)
    const latest = observe(store.applyFromLoginPayload({ data: account(1) }))
    if (outcome === 'success') boundary.industries[0].resolve()
    else boundary.industries[0].reject(new Error('superseded industry read failed'))
    await flushPromises()
    expect(old.result.settled).toBe(false)
    expect(latest.result.settled).toBe(false)
    expect(store.workspaceReady).toBe(false)
    await preferencesReady(1)
    boundary.industries[1].resolve()
    await Promise.all([old.done, latest.done])
    expect(old.result.error).toBeUndefined()
    expect(latest.result.error).toBeUndefined()
    expect(store.workspaceReady).toBe(true)
  })

  it.each(['success', 'error'] as const)('propagates the latest real failure to a superseded %s caller', async outcome => {
    const store = useAccountProfileStore()
    const old = observe(store.applyFromMeData(account(1)))
    await preferencesReady(0)
    const latest = observe(store.applyFromMeData(account(1)))
    await preferencesReady(1)
    if (outcome === 'success') boundary.industries[0].resolve()
    else boundary.industries[0].reject(new Error('superseded failure'))
    await flushPromises()
    expect(old.result.settled).toBe(false)
    const error = new Error('latest verified industry failed')
    boundary.industries[1].reject(error)
    await Promise.all([old.done, latest.done])
    expect(old.result.error).toBe(error)
    expect(latest.result.error).toBe(error)
    expect(store.workspaceReady).toBe(false)
  })

  it('does not let a cleared caller join a new login to the same account', async () => {
    const store = useAccountProfileStore()
    const old = observe(store.applyFromMeData(account(1)))
    await preferencesReady(0)
    store.clear(false)
    const latest = observe(store.applyFromLoginPayload({ data: account(1) }))
    boundary.industries[0].resolve()
    await old.done
    expect(old.result.error).toBeInstanceOf(Error)
    expect(latest.result.settled).toBe(false)
    expect(store.workspaceReady).toBe(false)
    await preferencesReady(2)
    boundary.industries[1].resolve()
    await latest.done
    expect(latest.result.error).toBeUndefined()
    expect(store.workspaceReady).toBe(true)
  })

  it('rejects both old scopes across A → B → A while the new A is still pending', async () => {
    const store = useAccountProfileStore()
    const firstA = observe(store.applyFromMeData(account(1)))
    const accountB = observe(store.applyFromMeData(account(2)))
    const currentA = observe(store.applyFromLoginPayload({ data: account(1) }))
    boundary.preferences[0].resolve(); boundary.preferences[1].resolve()
    await Promise.all([firstA.done, accountB.done])
    expect(firstA.result.error).toBeInstanceOf(Error)
    expect(accountB.result.error).toBeInstanceOf(Error)
    expect(currentA.result.settled).toBe(false)
    expect(store.workspaceReady).toBe(false)
    await preferencesReady(2)
    boundary.industries[0].resolve()
    await currentA.done
    expect(currentA.result.error).toBeUndefined()
    expect(store.workspaceReady).toBe(true)
  })

  it('rejects hydration from an invalidated auth session even without another account scope', async () => {
    const store = useAccountProfileStore()
    const old = observe(store.applyFromMeData(account(1)))
    await preferencesReady(0)
    invalidateEnterpriseSessionCache()
    boundary.industries[0].resolve()
    await old.done
    expect(old.result.error).toBeInstanceOf(Error)
    expect(store.workspaceReady).toBe(false)
  })

  it('does not let a pre-relogin caller join or release the new same-account login', async () => {
    const store = useAccountProfileStore()
    const old = observe(store.applyFromMeData(account(1)))
    await preferencesReady(0)
    invalidateEnterpriseSessionCache(); markEnterpriseSessionValid()
    const latest = observe(store.applyFromLoginPayload({ data: account(1) }))
    boundary.industries[0].resolve()
    await old.done
    expect(old.result.error).toBeInstanceOf(Error)
    expect(latest.result.settled).toBe(false)
    expect(store.workspaceReady).toBe(false)
    await preferencesReady(1)
    boundary.industries[1].resolve()
    await latest.done
    expect(latest.result.error).toBeUndefined()
    expect(store.workspaceReady).toBe(true)
  })
})

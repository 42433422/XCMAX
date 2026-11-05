import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { fetchMarketAccountOverview, fetchMarketLlmCatalog } from '@/api/marketAccount'
import { CACHE_KEYS, getCachedData, setCachedData } from '../../../mods/xcagi-model-payment-bridge/frontend/views/model-payment/mpMarketCache'
import { useMpMarketData } from '../../../mods/xcagi-model-payment-bridge/frontend/views/model-payment/useMpMarketData'

vi.mock('@/api/marketAccount', async (load) => ({
  ...await load<typeof import('@/api/marketAccount')>(),
  fetchMarketAccountOverview: vi.fn(),
  fetchMarketLlmCatalog: vi.fn(),
}))
let active: ReturnType<typeof effectScope>[] = []
const overview = (username: string) => ({ user: { username }, wallet: { balance: 123 }, membership: { label: username }, market_base_url: '' })
function account(id: number | null) {
  const value = id === null ? null : { tenantId: 9, marketUserId: id, localUserId: id, accountKind: 'enterprise' }
  setRuntimeTenantStorageScopeInput(value)
  updateProductReadAccountScope(value ?? undefined)
}
function mountData() {
  const owner = effectScope()
  active.push(owner)
  return owner.run(() => useMpMarketData({ isOffline: ref(false), dataSource: ref('network') }))!
}
beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  account(null)
  vi.mocked(fetchMarketLlmCatalog).mockResolvedValue({ providers: [] })
})
afterEach(() => { for (const owner of active) owner.stop(); active = [] })

describe('model service account isolation', () => {
  it('never restores an unowned legacy account cache', () => {
    account(2)
    localStorage.setItem(CACHE_KEYS.OVERVIEW, JSON.stringify({ data: overview('A'), timestamp: Date.now() }))
    expect(mountData().restoreFromCache()).toBe(false)
  })
  it('separates users within the same tenant and keeps their own offline snapshot', () => {
    account(1)
    setCachedData(CACHE_KEYS.OVERVIEW, overview('A'))
    account(2)
    expect(getCachedData(CACHE_KEYS.OVERVIEW)).toBeNull()
    setCachedData(CACHE_KEYS.OVERVIEW, overview('B'))
    account(1)
    expect(getCachedData(CACHE_KEYS.OVERVIEW)).toMatchObject({ user: { username: 'A' } })
  })
  it('retires pending account responses across A -> B -> A and clears visible data at logout', async () => {
    account(1)
    let finish!: (value: ReturnType<typeof overview>) => void
    vi.mocked(fetchMarketAccountOverview).mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const data = mountData()
    const old = data.refreshMarketOverview(undefined, true)
    account(2)
    account(1)
    finish(overview('old-A'))
    await old
    expect(data.marketOverview.value).toBeNull()
    expect(getCachedData(CACHE_KEYS.OVERVIEW)).toBeNull()
    vi.mocked(fetchMarketAccountOverview).mockResolvedValue(overview('current-A'))
    await data.refreshMarketOverview(undefined, true)
    expect(data.marketOverview.value?.user?.username).toBe('current-A')
    invalidateEnterpriseSessionCache()
    expect(data.marketOverview.value).toBeNull()
  })
  it('does not apply an old account failure to a new account', async () => {
    account(1)
    let fail!: (reason: unknown) => void
    vi.mocked(fetchMarketAccountOverview).mockReturnValue(new Promise((_, reject) => { fail = reject }))
    const data = mountData()
    const old = data.refreshMarketOverview(undefined, true)
    account(2)
    vi.mocked(fetchMarketAccountOverview).mockResolvedValue(overview('B'))
    await data.refreshMarketOverview(undefined, true)
    fail(Object.assign(new Error('old 401'), { status: 401 }))
    await old
    expect(data.marketOverview.value?.user?.username).toBe('B')
    expect(data.marketSyncWarning.value).toBe('')
  })
})

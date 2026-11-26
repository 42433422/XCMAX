import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '@/utils/apiBase'
import { fetchMarketCatalog } from '@/api/modStore'
import { buildMarketCatalogCacheKey, clearMarketCatalogCache, readMarketCatalogCache } from '@/utils/marketCatalogCache'
import { useModStoreCatalog } from './useModStoreCatalog'
import { useModStoreState } from './useModStoreState'

vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn() }))
vi.mock('@/api/modStore', () => ({ fetchMarketCatalog: vi.fn() }))
vi.mock('@/utils/tenantStorageScope', () => ({ resolveTenantStorageScopeFromRuntime: () => 'catalog-tab-test' }))

function persistedCatalogKeys(): string[] {
  return Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index)!)
    .filter(key => key.startsWith('xcagi_market_catalog_v1:'))
}

describe('market catalog tab selection boundary', () => {
  beforeEach(() => {
    clearMarketCatalogCache()
    vi.clearAllMocks()
    vi.mocked(apiFetch).mockImplementation(async () => new Response(JSON.stringify({
      success: true, data: { available: [] },
    })))
    vi.mocked(fetchMarketCatalog).mockResolvedValue({ items: [], total: 0, collection: '' })
  })

  it.each(['__proto__', 'constructor', 'toString', 'office\narbitrary-input', 'not-a-catalog'])(
    'does not send or cache an unsupported catalog tab: %s',
    async (input) => {
      const state = useModStoreState()
      const catalog = useModStoreCatalog(state)
      await catalog.switchTab(input)

      expect(persistedCatalogKeys()).toEqual([])
      expect(fetchMarketCatalog).not.toHaveBeenCalled()
      expect(state.currentTab.value).toBe('host_foundation')
      expect(state.filterInstalled.value).toBe(false)
      expect(apiFetch).toHaveBeenCalledWith('/api/mod-store/catalog', { timeoutMs: 90_000 })
    },
  )

  it('preserves every navigation category, installed filtering and market cache entries', async () => {
    const state = useModStoreState()
    const catalog = useModStoreCatalog(state)
    for (const { id } of catalog.storeNavTabs) {
      state.marketType.value = id === 'industry_mod' ? 'module' : 'employee'
      await catalog.switchTab(id)
      expect(state.currentTab.value).toBe(id)
      expect(state.filterInstalled.value).toBe(id === 'installed')
      if (catalog.isMarketCollectionTab(id)) {
        const key = buildMarketCatalogCacheKey(id)
        expect(readMarketCatalogCache(key)?.tab).toBe(id)
        const storedKey = persistedCatalogKeys().find(value => decodeURIComponent(value).includes(JSON.stringify(key)))
        expect(storedKey).toBeDefined()
        const stored = JSON.parse(sessionStorage.getItem(storedKey!)!)
        expect(stored).toEqual({ items: [], fetchedAt: expect.any(Number) })
        expect(stored).not.toHaveProperty('tab')
      }
    }
    expect(persistedCatalogKeys()).toHaveLength(4)
    expect(fetchMarketCatalog).toHaveBeenCalledTimes(4)
  })
})

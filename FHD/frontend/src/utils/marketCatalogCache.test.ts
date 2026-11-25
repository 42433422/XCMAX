import { describe, expect, it, beforeEach, vi } from 'vitest'

const scope = vi.hoisted(() => ({ value: 'tenant-a' }))
vi.mock('@/utils/tenantStorageScope', () => ({
  resolveTenantStorageScopeFromRuntime: () => scope.value,
}))
import {
  MARKET_CACHE_MAX_ENTRIES,
  buildMarketCatalogCacheKey,
  clearMarketCatalogCache,
  isMarketCatalogCacheFresh,
  readMarketCatalogCache,
  writeMarketCatalogCache,
} from './marketCatalogCache'

describe('marketCatalogCache', () => {
  beforeEach(() => {
    scope.value = 'tenant-a'
    clearMarketCatalogCache()
  })

  it('builds stable keys', () => {
    expect(buildMarketCatalogCacheKey('office', '  ')).toBe('v2:office:')
    expect(buildMarketCatalogCacheKey('office', 'excel')).toBe('v2:office:excel')
  })

  it('round-trips cache entries', () => {
    const key = buildMarketCatalogCacheKey('office')
    writeMarketCatalogCache(key, 'office', [{ id: 'excel-generate-employee', name: 'Excel' } as never])
    const hit = readMarketCatalogCache(key)
    expect(hit?.items).toHaveLength(1)
    expect(isMarketCatalogCacheFresh(hit)).toBe(true)
  })

  it('bounds persisted and memory cache entries across repeated searches', () => {
    vi.useFakeTimers()
    try {
      for (let i = 0; i < MARKET_CACHE_MAX_ENTRIES + 5; i++) {
        vi.setSystemTime(new Date(1700000000000 + i * 1000))
        writeMarketCatalogCache(buildMarketCatalogCacheKey('office', String(i)), 'office', [{ id: String(i) } as never])
      }
      expect(Array.from({ length: sessionStorage.length }, (_, i) => sessionStorage.key(i))
        .filter(key => key?.startsWith('xcagi_market_catalog_v1:'))).toHaveLength(MARKET_CACHE_MAX_ENTRIES)
      expect(readMarketCatalogCache(buildMarketCatalogCacheKey('office', '0'))).toBeNull()
      expect(readMarketCatalogCache(buildMarketCatalogCacheKey('office', String(MARKET_CACHE_MAX_ENTRIES + 4)))?.items[0].id).toBe(String(MARKET_CACHE_MAX_ENTRIES + 4))
    } finally {
      vi.useRealTimers()
    }
  })

  it('skips oversized payloads without truncating a result', () => {
    const key = buildMarketCatalogCacheKey('office', 'large')
    writeMarketCatalogCache(key, 'office', [{ id: 'large', name: 'x'.repeat(300 * 1024) } as never])
    expect(readMarketCatalogCache(key)).toBeNull()
  })

  it('isolates memory caches and targeted removal across tenant switches', () => {
    const key = buildMarketCatalogCacheKey('office')
    scope.value = 'tenant-a'
    writeMarketCatalogCache(key, 'office', [{ id: 'private-a' } as never])
    scope.value = 'tenant-b'
    expect(readMarketCatalogCache(key)).toBeNull()
    writeMarketCatalogCache(key, 'office', [{ id: 'private-b' } as never])
    clearMarketCatalogCache(key)
    expect(readMarketCatalogCache(key)).toBeNull()
    scope.value = 'tenant-a'
    expect(readMarketCatalogCache(key)?.items[0].id).toBe('private-a')
  })
})

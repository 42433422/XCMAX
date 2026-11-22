import { describe, expect, it, beforeEach, vi } from 'vitest'

const scope = vi.hoisted(() => ({ value: 'tenant-a' }))
vi.mock('@/utils/tenantStorageScope', () => ({
  resolveTenantStorageScopeFromRuntime: () => scope.value,
}))
import {
  buildMarketCatalogCacheKey,
  clearMarketCatalogCache,
  isMarketCatalogCacheFresh,
  readMarketCatalogCache,
  writeMarketCatalogCache,
} from './marketCatalogCache'

describe('marketCatalogCache', () => {
  beforeEach(() => {
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

/**
 * marketCatalogCache 函数覆盖率补齐测试
 * 目标：覆盖所有未测分支（stale memory、sessionStorage 异常、无效 JSON、过期缓存、clearMarketCatalogCache 等）
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'
import {
  buildMarketCatalogCacheKey,
  clearMarketCatalogCache,
  isMarketCatalogCacheFresh,
  readMarketCatalogCache,
  writeMarketCatalogCache,
} from './marketCatalogCache'

// Mock tenantStorageScope 以避免依赖运行时环境
vi.mock('@/utils/tenantStorageScope', () => ({
  resolveTenantStorageScopeFromRuntime: () => 'test-tenant',
}))

describe('marketCatalogCache – buildMarketCatalogCacheKey', () => {
  it('tab 和 q 组合 key', () => {
    expect(buildMarketCatalogCacheKey('office', 'excel')).toBe('office:excel')
  })

  it('q 为空字符串时', () => {
    expect(buildMarketCatalogCacheKey('office', '')).toBe('office:')
  })

  it('q 为空白字符串时 trim 后为空', () => {
    expect(buildMarketCatalogCacheKey('office', '   ')).toBe('office:')
  })

  it('q 为 undefined 时使用默认空字符串', () => {
    expect(buildMarketCatalogCacheKey('office')).toBe('office:')
  })

  it('tab 为空字符串时', () => {
    expect(buildMarketCatalogCacheKey('', 'query')).toBe(':query')
  })

  it('q 含前后空格时 trim', () => {
    expect(buildMarketCatalogCacheKey('all', '  keyword  ')).toBe('all:keyword')
  })
})

describe('marketCatalogCache – writeMarketCatalogCache + readMarketCatalogCache', () => {
  beforeEach(() => {
    clearMarketCatalogCache()
  })

  it('写入后能从内存读取', () => {
    const key = buildMarketCatalogCacheKey('office')
    const items = [{ id: 'mod-1', name: 'Mod 1' }] as never[]
    writeMarketCatalogCache(key, 'office', items)
    const entry = readMarketCatalogCache(key)
    expect(entry).not.toBeNull()
    expect(entry!.items).toHaveLength(1)
    expect(entry!.tab).toBe('office')
    expect(typeof entry!.fetchedAt).toBe('number')
  })

  it('写入空 items 数组也能读取', () => {
    const key = buildMarketCatalogCacheKey('office')
    writeMarketCatalogCache(key, 'office', [])
    const entry = readMarketCatalogCache(key)
    expect(entry).not.toBeNull()
    expect(entry!.items).toHaveLength(0)
  })

  it('内存缓存过期后从 sessionStorage 读取', () => {
    const key = buildMarketCatalogCacheKey('office')
    const items = [{ id: 'mod-1', name: 'Mod 1' }] as never[]
    writeMarketCatalogCache(key, 'office', items)
    // 使用负 ttl 使内存缓存过期
    const entry = readMarketCatalogCache(key, -1)
    // 内存缓存过期，但 sessionStorage 中的条目 items 非空，应返回该条目
    expect(entry).not.toBeNull()
    expect(entry!.items).toHaveLength(1)
  })

  it('内存和 sessionStorage 都无数据时返回 null', () => {
    const key = buildMarketCatalogCacheKey('nonexistent')
    const entry = readMarketCatalogCache(key)
    expect(entry).toBeNull()
  })

  it('sessionStorage 中有无效 JSON 时回退到内存', () => {
    const key = buildMarketCatalogCacheKey('office')
    // 直接在 sessionStorage 中写入无效 JSON
    const prefix = 'xcagi_market_catalog_v1:'
    sessionStorage.setItem(`${prefix}test-tenant:${key}`, 'invalid json')
    const entry = readMarketCatalogCache(key)
    expect(entry).toBeNull()
  })

  it('sessionStorage 中有无效结构（items 非数组）时返回 null', () => {
    const key = buildMarketCatalogCacheKey('office')
    const prefix = 'xcagi_market_catalog_v1:'
    const badEntry = { items: 'not-an-array', fetchedAt: Date.now(), tab: 'office' }
    sessionStorage.setItem(`${prefix}test-tenant:${key}`, JSON.stringify(badEntry))
    const entry = readMarketCatalogCache(key)
    expect(entry).toBeNull()
  })

  it('sessionStorage 中有无效结构（fetchedAt 非数字）时返回 null', () => {
    const key = buildMarketCatalogCacheKey('office')
    const prefix = 'xcagi_market_catalog_v1:'
    const badEntry = { items: [{ id: '1' }], fetchedAt: 'not-a-number', tab: 'office' }
    sessionStorage.setItem(`${prefix}test-tenant:${key}`, JSON.stringify(badEntry))
    const entry = readMarketCatalogCache(key)
    expect(entry).toBeNull()
  })

  it('sessionStorage 中缓存过期且 items 非空时仍返回该条目', () => {
    const key = buildMarketCatalogCacheKey('office')
    const items = [{ id: 'mod-1', name: 'Mod 1' }] as never[]
    writeMarketCatalogCache(key, 'office', items)
    // 使用负 ttl 使 sessionStorage 缓存过期
    const entry = readMarketCatalogCache(key, -1)
    // 过期但 items 非空，应返回 parsed
    expect(entry).not.toBeNull()
    expect(entry!.items).toHaveLength(1)
  })

  it('sessionStorage 中缓存过期且 items 为空时返回 null', () => {
    const key = buildMarketCatalogCacheKey('office')
    writeMarketCatalogCache(key, 'office', [])
    // 使用负 ttl 使缓存过期
    const entry = readMarketCatalogCache(key, -1)
    // 过期且 items 为空，应返回 null
    expect(entry).toBeNull()
  })
})

describe('marketCatalogCache – isMarketCatalogCacheFresh', () => {
  beforeEach(() => {
    clearMarketCatalogCache()
  })

  it('entry 为 null 时返回 false', () => {
    expect(isMarketCatalogCacheFresh(null)).toBe(false)
  })

  it('entry 为 undefined 时返回 false', () => {
    expect(isMarketCatalogCacheFresh(undefined as never)).toBe(false)
  })

  it('items 为空数组时返回 false', () => {
    const key = buildMarketCatalogCacheKey('office')
    writeMarketCatalogCache(key, 'office', [])
    const entry = readMarketCatalogCache(key)
    expect(isMarketCatalogCacheFresh(entry)).toBe(false)
  })

  it('items 非空且未过期时返回 true', () => {
    const key = buildMarketCatalogCacheKey('office')
    writeMarketCatalogCache(key, 'office', [{ id: '1' }] as never[])
    const entry = readMarketCatalogCache(key)
    expect(isMarketCatalogCacheFresh(entry)).toBe(true)
  })

  it('items 非空但已过期时返回 false', () => {
    const key = buildMarketCatalogCacheKey('office')
    writeMarketCatalogCache(key, 'office', [{ id: '1' }] as never[])
    const entry = readMarketCatalogCache(key)
    // 使用负 ttl 使缓存过期
    expect(isMarketCatalogCacheFresh(entry, -1)).toBe(false)
  })

  it('自定义 ttl 生效', () => {
    const key = buildMarketCatalogCacheKey('office')
    writeMarketCatalogCache(key, 'office', [{ id: '1' }] as never[])
    const entry = readMarketCatalogCache(key)
    // 使用很大的 ttl 确保未过期
    expect(isMarketCatalogCacheFresh(entry, 999999999999)).toBe(true)
  })
})

describe('marketCatalogCache – clearMarketCatalogCache', () => {
  beforeEach(() => {
    clearMarketCatalogCache()
  })

  it('清除指定 key 后读取返回 null', () => {
    const key = buildMarketCatalogCacheKey('office')
    writeMarketCatalogCache(key, 'office', [{ id: '1' }] as never[])
    expect(readMarketCatalogCache(key)).not.toBeNull()
    clearMarketCatalogCache(key)
    expect(readMarketCatalogCache(key)).toBeNull()
  })

  it('清除指定 key 不影响其他 key', () => {
    const key1 = buildMarketCatalogCacheKey('office')
    const key2 = buildMarketCatalogCacheKey('workflow')
    writeMarketCatalogCache(key1, 'office', [{ id: '1' }] as never[])
    writeMarketCatalogCache(key2, 'workflow', [{ id: '2' }] as never[])
    clearMarketCatalogCache(key1)
    expect(readMarketCatalogCache(key1)).toBeNull()
    expect(readMarketCatalogCache(key2)).not.toBeNull()
  })

  it('不传 key 时清除所有缓存', () => {
    const key1 = buildMarketCatalogCacheKey('office')
    const key2 = buildMarketCatalogCacheKey('workflow')
    writeMarketCatalogCache(key1, 'office', [{ id: '1' }] as never[])
    writeMarketCatalogCache(key2, 'workflow', [{ id: '2' }] as never[])
    clearMarketCatalogCache()
    expect(readMarketCatalogCache(key1)).toBeNull()
    expect(readMarketCatalogCache(key2)).toBeNull()
  })

  it('清除不存在的 key 不报错', () => {
    expect(() => clearMarketCatalogCache('nonexistent-key')).not.toThrow()
  })
})

describe('marketCatalogCache – sessionStorage 异常处理', () => {
  beforeEach(() => {
    clearMarketCatalogCache()
  })

  it('writeMarketCatalogCache 在 sessionStorage.setItem 抛错时不崩溃', () => {
    const originalSetItem = sessionStorage.setItem.bind(sessionStorage)
    sessionStorage.setItem = vi.fn(() => {
      throw new Error('QuotaExceededError')
    })
    const key = buildMarketCatalogCacheKey('office')
    expect(() => writeMarketCatalogCache(key, 'office', [{ id: '1' }] as never[])).not.toThrow()
    // 内存缓存仍然应该有数据
    const entry = readMarketCatalogCache(key)
    expect(entry).not.toBeNull()
    sessionStorage.setItem = originalSetItem
  })

  it('readMarketCatalogCache 在 sessionStorage.getItem 抛错时回退到内存', () => {
    const key = buildMarketCatalogCacheKey('office')
    writeMarketCatalogCache(key, 'office', [{ id: '1' }] as never[])
    const originalGetItem = sessionStorage.getItem.bind(sessionStorage)
    sessionStorage.getItem = vi.fn(() => {
      throw new Error('SecurityError')
    })
    // 内存缓存有数据且未过期，应直接返回
    const entry = readMarketCatalogCache(key)
    expect(entry).not.toBeNull()
    expect(entry!.items).toHaveLength(1)
    sessionStorage.getItem = originalGetItem
  })

  it('clearMarketCatalogCache 在 sessionStorage.removeItem 抛错时不崩溃', () => {
    const originalRemoveItem = sessionStorage.removeItem.bind(sessionStorage)
    sessionStorage.removeItem = vi.fn(() => {
      throw new Error('SecurityError')
    })
    expect(() => clearMarketCatalogCache('some-key')).not.toThrow()
    sessionStorage.removeItem = originalRemoveItem
  })

  it('clearMarketCatalogCache（全部）在 sessionStorage.key 抛错时不崩溃', () => {
    const originalKey = sessionStorage.key.bind(sessionStorage)
    sessionStorage.key = vi.fn(() => {
      throw new Error('SecurityError')
    })
    expect(() => clearMarketCatalogCache()).not.toThrow()
    sessionStorage.key = originalKey
  })
})

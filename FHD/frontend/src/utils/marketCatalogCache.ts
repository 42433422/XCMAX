import type { ModCatalogItemUi } from '@/types/modCatalog'
import { resolveTenantStorageScopeFromRuntime } from '@/utils/tenantStorageScope'

const STORAGE_PREFIX = 'xcagi_market_catalog_v1:'
const DEFAULT_TTL_MS = 30 * 60 * 1000

export interface MarketCatalogCacheEntry {
  items: ModCatalogItemUi[]
  fetchedAt: number
  tab: string
}

const memory = new Map<string, MarketCatalogCacheEntry>()

function storageKey(key: string): string {
  return `${STORAGE_PREFIX}${resolveTenantStorageScopeFromRuntime()}:${key}`
}

export function buildMarketCatalogCacheKey(tab: string, q = ''): string {
  // v2：市场拉取上限由 80 提升到 200，旧缓存键作废，避免继续显示截断结果。
  return `v2:${tab}:${q.trim()}`
}

export function readMarketCatalogCache(key: string, ttlMs = DEFAULT_TTL_MS): MarketCatalogCacheEntry | null {
  const scopedKey = storageKey(key)
  const mem = memory.get(scopedKey)
  if (mem && Date.now() - mem.fetchedAt <= ttlMs) {
    return mem
  }

  try {
    const raw = sessionStorage.getItem(scopedKey)
    if (!raw) return mem && mem.items.length ? mem : null
    const parsed = JSON.parse(raw) as MarketCatalogCacheEntry
    if (!parsed || !Array.isArray(parsed.items) || typeof parsed.fetchedAt !== 'number') {
      return mem && mem.items.length ? mem : null
    }
    parsed.tab = key.split(':')[1] || ''
    memory.set(scopedKey, parsed)
    if (Date.now() - parsed.fetchedAt > ttlMs) {
      return parsed.items.length ? parsed : null
    }
    return parsed
  } catch {
    return mem && mem.items.length ? mem : null
  }
}

export function isMarketCatalogCacheFresh(entry: MarketCatalogCacheEntry | null, ttlMs = DEFAULT_TTL_MS): boolean {
  if (!entry?.items?.length) return false
  return Date.now() - entry.fetchedAt <= ttlMs
}

// Public catalog fields only. URLs and package locators stay out of web storage,
// and the tab label is not persisted: it can be recovered from the cache key and
// must not leak lastEmployeeTab-style values into sessionStorage as clear text.
const PERSISTED_ITEM_OMIT = ['download_url', 'catalog_base_url', 'package_file', 'artifact'] as const

function persistableItems(items: ModCatalogItemUi[]): ModCatalogItemUi[] {
  return items.map((item) => {
    const publicItem = { ...item }
    for (const field of PERSISTED_ITEM_OMIT) {
      delete publicItem[field]
    }
    return publicItem
  })
}

export function writeMarketCatalogCache(key: string, tab: string, items: ModCatalogItemUi[]): void {
  const scopedKey = storageKey(key)
  const entry: MarketCatalogCacheEntry = {
    items,
    fetchedAt: Date.now(),
    tab,
  }
  memory.set(scopedKey, entry)
  try {
    sessionStorage.setItem(
      scopedKey,
      JSON.stringify({ items: persistableItems(items), fetchedAt: entry.fetchedAt }),
    )
  } catch {
    /* quota or private mode */
  }
}

export function clearMarketCatalogCache(key?: string): void {
  if (key) {
    const scopedKey = storageKey(key)
    memory.delete(scopedKey)
    try {
      sessionStorage.removeItem(scopedKey)
    } catch {
      /* ignore */
    }
    return
  }
  memory.clear()
  try {
    for (let i = sessionStorage.length - 1; i >= 0; i -= 1) {
      const k = sessionStorage.key(i)
      if (k?.startsWith(STORAGE_PREFIX)) {
        sessionStorage.removeItem(k)
      }
    }
  } catch {
    /* ignore */
  }
}

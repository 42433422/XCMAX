import type { ModInfo } from '@/api/modStore'
import { resolveTenantStorageScopeFromRuntime } from '@/utils/tenantStorageScope'

const STORAGE_PREFIX = 'xcagi_market_catalog_v1:'
const DEFAULT_TTL_MS = 30 * 60 * 1000

export interface MarketCatalogCacheEntry {
  items: ModInfo[]
  fetchedAt: number
  tab: string
}

const memory = new Map<string, MarketCatalogCacheEntry>()

function storageKey(key: string): string {
  return `${STORAGE_PREFIX}${resolveTenantStorageScopeFromRuntime()}:${key}`
}

export function buildMarketCatalogCacheKey(tab: string, q = ''): string {
  return `${tab}:${q.trim()}`
}

export function readMarketCatalogCache(
  key: string,
  ttlMs = DEFAULT_TTL_MS,
): MarketCatalogCacheEntry | null {
  const mem = memory.get(key)
  if (mem && Date.now() - mem.fetchedAt <= ttlMs) {
    return mem
  }

  try {
    const raw = sessionStorage.getItem(storageKey(key))
    if (!raw) return mem && mem.items.length ? mem : null
    const parsed = JSON.parse(raw) as MarketCatalogCacheEntry
    if (!parsed || !Array.isArray(parsed.items) || typeof parsed.fetchedAt !== 'number') {
      return mem && mem.items.length ? mem : null
    }
    memory.set(key, parsed)
    if (Date.now() - parsed.fetchedAt > ttlMs) {
      return parsed.items.length ? parsed : null
    }
    return parsed
  } catch {
    return mem && mem.items.length ? mem : null
  }
}

export function isMarketCatalogCacheFresh(
  entry: MarketCatalogCacheEntry | null,
  ttlMs = DEFAULT_TTL_MS,
): boolean {
  if (!entry?.items?.length) return false
  return Date.now() - entry.fetchedAt <= ttlMs
}

export function writeMarketCatalogCache(key: string, tab: string, items: ModInfo[]): void {
  const entry: MarketCatalogCacheEntry = {
    items,
    fetchedAt: Date.now(),
    tab,
  }
  memory.set(key, entry)
  try {
    sessionStorage.setItem(storageKey(key), JSON.stringify(entry))
  } catch {
    /* quota or private mode */
  }
}

export function clearMarketCatalogCache(key?: string): void {
  if (key) {
    memory.delete(key)
    try {
      sessionStorage.removeItem(storageKey(key))
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

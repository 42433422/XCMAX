import type { ModCatalogItemUi } from '@/types/modCatalog'
import { resolveTenantStorageScopeFromRuntime } from '@/utils/tenantStorageScope'
import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'

const STORAGE_PREFIX = 'xcagi_market_catalog_v1:'
const DEFAULT_TTL_MS = 30 * 60 * 1000
export const MARKET_CACHE_MAX_ENTRIES = 24
// Limit both memory and persisted serialized payloads without silently
// truncating a business result. Oversized results are fetched again.
const MAX_ENTRY_CHARS = 256 * 1024

export interface MarketCatalogCacheEntry {
  items: ModCatalogItemUi[]
  fetchedAt: number
  tab: string
}

const memory = new Map<string, MarketCatalogCacheEntry>()

function remember(key: string, entry: MarketCatalogCacheEntry): void {
  memory.delete(key)
  memory.set(key, entry)
  while (memory.size > MARKET_CACHE_MAX_ENTRIES) {
    const oldest = memory.keys().next().value
    if (oldest === undefined) break
    memory.delete(oldest)
  }
}

function pruneStorage(currentKey: string): void {
  const entries: { key: string; fetchedAt: number }[] = []
  for (let i = 0; i < sessionStorage.length; i++) {
    const key = sessionStorage.key(i)
    if (!key?.startsWith(STORAGE_PREFIX) || key === currentKey) continue
    try {
      const raw = sessionStorage.getItem(key) || ''
      const parsed = raw.length <= MAX_ENTRY_CHARS ? JSON.parse(raw) : null
      entries.push({ key, fetchedAt: Number(parsed?.fetchedAt) || 0 })
    } catch {
      entries.push({ key, fetchedAt: 0 })
    }
  }
  entries.sort((a, b) => b.fetchedAt - a.fetchedAt)
  for (const entry of entries.slice(MARKET_CACHE_MAX_ENTRIES - 1)) sessionStorage.removeItem(entry.key)
}

function storageKey(key: string): string {
  const account = getRuntimeTenantStorageScopeInput()
  // A tenant can contain multiple accounts. Keep their catalog projections separate,
  // and bypass the short-lived scope memo when accessing account-specific data.
  const scope = resolveTenantStorageScopeFromRuntime(true)
  const principal = [account?.marketUserId ?? null, account?.localUserId ?? null,
    account?.marketUsername ?? '', account?.accountKind ?? '']
  return `${STORAGE_PREFIX}v3:${encodeURIComponent(JSON.stringify([scope, principal, key]))}`
}

function validTimestamp(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= Date.now()
}

// Cache entries are snapshots, not writable view state.
function copyEntry(entry: MarketCatalogCacheEntry): MarketCatalogCacheEntry {
  return JSON.parse(JSON.stringify(entry)) as MarketCatalogCacheEntry
}

export function buildMarketCatalogCacheKey(tab: string, q = ''): string {
  // v2：市场拉取上限由 80 提升到 200，旧缓存键作废，避免继续显示截断结果。
  return `v2:${tab}:${q.trim()}`
}

export function readMarketCatalogCache(key: string, ttlMs = DEFAULT_TTL_MS): MarketCatalogCacheEntry | null {
  const scopedKey = storageKey(key)
  let mem = memory.get(scopedKey)
  if (mem && !validTimestamp(mem.fetchedAt)) {
    memory.delete(scopedKey)
    mem = undefined
  }
  if (mem && Date.now() - mem.fetchedAt <= ttlMs) {
    remember(scopedKey, mem)
    return copyEntry(mem)
  }

  // Preserve explicit stale-while-revalidate behavior for nonempty public catalog
  // snapshots, but never present an invalid clock or corrupted entry as fresh.
  const stale = () => mem?.items.length ? copyEntry(mem) : null
  try {
    const raw = sessionStorage.getItem(scopedKey)
    if (!raw) return stale()
    if (raw.length > MAX_ENTRY_CHARS) {
      sessionStorage.removeItem(scopedKey)
      return stale()
    }
    const parsed = JSON.parse(raw) as MarketCatalogCacheEntry
    if (!parsed || !Array.isArray(parsed.items) || !validTimestamp(parsed.fetchedAt)) {
      sessionStorage.removeItem(scopedKey)
      return stale()
    }
    parsed.tab = key.split(':')[1] || ''
    // An older persisted snapshot cannot overwrite a newer in-memory one.
    const entry = mem && mem.fetchedAt >= parsed.fetchedAt ? mem : parsed
    remember(scopedKey, entry)
    if (Date.now() - entry.fetchedAt > ttlMs && !entry.items.length) return null
    return copyEntry(entry)
  } catch {
    return stale()
  }
}

export function isMarketCatalogCacheFresh(entry: MarketCatalogCacheEntry | null, ttlMs = DEFAULT_TTL_MS): boolean {
  if (!entry?.items?.length || !validTimestamp(entry.fetchedAt)) return false
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
    items: items.map(item => {
      const snapshot = { ...item }
      delete snapshot.installationInProgress
      delete snapshot.uninstallationInProgress
      delete snapshot.updateInProgress
      return snapshot
    }),
    fetchedAt: Date.now(),
    tab,
  }
  // Bound the full in-memory entry as well as the public storage projection.
  let serialized: string
  try {
    if (JSON.stringify(entry).length > MAX_ENTRY_CHARS) {
      clearMarketCatalogCache(key)
      return
    }
    serialized = JSON.stringify({ items: persistableItems(entry.items), fetchedAt: entry.fetchedAt })
    if (serialized.length > MAX_ENTRY_CHARS) {
      clearMarketCatalogCache(key)
      return
    }
  } catch {
    clearMarketCatalogCache(key)
    return
  }
  remember(scopedKey, copyEntry(entry))
  try {
    pruneStorage(scopedKey)
    sessionStorage.setItem(scopedKey, serialized)
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

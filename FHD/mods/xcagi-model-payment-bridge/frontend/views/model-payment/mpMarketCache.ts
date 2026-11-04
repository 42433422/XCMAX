import { MARKET_ACCOUNT_CACHE_KEYS, marketAccountOwner } from '@/api/marketAccount'

export const CACHE_KEYS = { OVERVIEW: MARKET_ACCOUNT_CACHE_KEYS[0], LLM_CATALOG: MARKET_ACCOUNT_CACHE_KEYS[1] } as const
export const CACHE_TTL = { OVERVIEW: 30_000, LLM_CATALOG: 30 * 60_000 } as const

export const marketCacheOwner = marketAccountOwner

interface CacheEntry<T> { owner: string; data: T; timestamp: number }

function readEntry<T>(key: string, owner: string | null): CacheEntry<T> | null {
  try {
    // Legacy snapshots have no provable owner and must never be adopted by a new login.
    window.localStorage.removeItem(key)
    if (!owner) return null
    const raw = window.localStorage.getItem(`${key}:${owner}`)
    if (!raw) return null
    const entry = JSON.parse(raw) as CacheEntry<T>
    return entry.owner === owner && Number.isFinite(entry.timestamp) ? entry : null
  } catch { return null }
}

export function getCachedData<T>(key: string, owner = marketCacheOwner()): T | null {
  return readEntry<T>(key, owner)?.data ?? null
}

export function setCachedData<T>(key: string, data: T, owner = marketCacheOwner()): void {
  if (!owner) return
  try {
    window.localStorage.removeItem(key)
    window.localStorage.setItem(`${key}:${owner}`, JSON.stringify({ owner, data, timestamp: Date.now() }))
  } catch { /* Private mode or storage quota; live data remains usable. */ }
}

export function clearCachedMarketData(owner = marketCacheOwner()): void {
  try {
    for (const key of Object.values(CACHE_KEYS)) {
      window.localStorage.removeItem(key)
      if (owner) window.localStorage.removeItem(`${key}:${owner}`)
    }
  } catch { /* Storage may be unavailable. */ }
}

export function getCacheAge(key: string, owner = marketCacheOwner()): number | null {
  const entry = readEntry(key, owner)
  return entry ? Math.max(0, Date.now() - entry.timestamp) : null
}

export function formatCacheAge(ms: number): string {
  if (ms < 60_000) return '刚刚'
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)} 分钟前`
  return `${Math.floor(ms / 3_600_000)} 小时前`
}

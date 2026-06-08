import type { RouteLocationNormalized } from 'vue-router'
import { setAuthTokens } from './tokenStore'

const HASH_PREFIX = 'xcagi_mt='
export const FHD_MARKET_QUERY_KEY = 'xcagi_mt'

function extractFromHashString(hash: string): string {
  const rawHash = (hash || '').replace(/^#/, '')
  if (!rawHash.startsWith(HASH_PREFIX)) return ''
  try {
    return decodeURIComponent(rawHash.slice(HASH_PREFIX.length).trim())
  } catch {
    return ''
  }
}

/**
 * 从 FHD 跳转带来的 hash（#xcagi_mt=…）或 query（?xcagi_mt=…）解析修茈 JWT。
 * 优先用路由对象；少数环境下 hash 尚未挂到 route 上时再读 window.location。
 */
export function extractFhdMarketTokenFromRoute(to: RouteLocationNormalized): string {
  let t = extractFromHashString(to.hash || '')
  if (t) return t
  if (typeof window !== 'undefined' && window.location.hash) {
    t = extractFromHashString(window.location.hash)
    if (t) return t
  }
  const q = to.query[FHD_MARKET_QUERY_KEY]
  const raw = Array.isArray(q) ? q[0] : q
  if (typeof raw === 'string' && raw.trim()) return raw.trim()
  if (typeof window !== 'undefined') {
    try {
      const sp = new URLSearchParams(window.location.search).get(FHD_MARKET_QUERY_KEY)
      if (sp?.trim()) return sp.trim()
    } catch {
      /* ignore */
    }
  }
  return ''
}

export function fhdHandoffNeedsStrip(to: RouteLocationNormalized): boolean {
  const h = (to.hash || '').replace(/^#/, '')
  if (h.startsWith(HASH_PREFIX)) return true
  if (to.query && FHD_MARKET_QUERY_KEY in to.query) return true
  if (typeof window !== 'undefined' && window.location.hash) {
    if (extractFromHashString(window.location.hash)) return true
  }
  return false
}

/** 仅写入 token，供测试或非路由入口复用 */
export function applyFhdMarketToken(token: string): void {
  const t = (token || '').trim()
  if (!t) return
  setAuthTokens({ access_token: t })
}

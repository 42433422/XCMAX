import { LS_MARKET_USER_JSON, type MarketUserProfile } from '@/api/marketAccount'
import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'

export type TenantStorageScopeInput = {
  tenantId?: number | null
  marketUserId?: number | string | null
  /** FHD 本地 users.id（/api/auth/me 下发，无 tenant 时仍可用于隔离） */
  localUserId?: number | string | null
  marketUsername?: string | null
  accountKind?: string | null
}

let cachedScope = ''
let cachedScopeAt = 0
const SCOPE_CACHE_MS = 500

function readMarketUserFromStorage(): MarketUserProfile | null {
  if (typeof localStorage === 'undefined') return null
  try {
    const raw = localStorage.getItem(LS_MARKET_USER_JSON)
    if (!raw) return null
    const parsed = JSON.parse(raw) as MarketUserProfile
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

/**
 * 客户端持久化隔离域（与服务器会话对齐）：
 * tenant_id → 市场用户 id → FHD local_user_id → 用户名 → admin → local（仅未登录）
 */
export function resolveTenantStorageScope(input?: TenantStorageScopeInput): string {
  const tid = input?.tenantId
  if (tid != null && Number.isFinite(Number(tid)) && Number(tid) > 0) {
    return `tenant:${Number(tid)}`
  }
  const uid = input?.marketUserId
  if (uid != null && String(uid).trim()) {
    return `user:${String(uid).trim()}`
  }
  const lid = input?.localUserId
  if (lid != null && String(lid).trim()) {
    return `session:${String(lid).trim()}`
  }
  const uname = String(input?.marketUsername || '').trim()
  if (uname) return `user:${uname}`
  const kind = String(input?.accountKind || '').trim()
  if (kind === 'admin') return 'platform:admin'
  return 'local'
}

export function setTenantStorageScopeCache(scope: string): void {
  cachedScope = scope
  cachedScopeAt = Date.now()
}

export function invalidateTenantStorageScopeCache(): void {
  cachedScope = ''
  cachedScopeAt = 0
}

function resolveScopeInputFromRuntime(): TenantStorageScopeInput {
  const fromSession = getRuntimeTenantStorageScopeInput()
  if (fromSession) return fromSession
  const market = readMarketUserFromStorage()
  return {
    marketUserId: market?.id,
    marketUsername: market?.username,
    accountKind: market?.is_admin ? 'admin' : 'enterprise',
  }
}

/** 优先已登录会话（accountProfile），其次市场 localStorage JSON。 */
export function resolveTenantStorageScopeFromRuntime(force = false): string {
  const now = Date.now()
  if (!force && cachedScope && now - cachedScopeAt < SCOPE_CACHE_MS) {
    return cachedScope
  }
  const scope = resolveTenantStorageScope(resolveScopeInputFromRuntime())
  setTenantStorageScopeCache(scope)
  return scope
}

export function buildTenantScopedStorageKey(baseKey: string, scope?: string): string {
  const s = scope || resolveTenantStorageScopeFromRuntime()
  return `${baseKey}:${s}`
}

export function readTenantScopedStorageItem(baseKey: string, scope?: string): string | null {
  if (typeof localStorage === 'undefined') return null
  try {
    return localStorage.getItem(buildTenantScopedStorageKey(baseKey, scope))
  } catch {
    return null
  }
}

export function writeTenantScopedStorageItem(
  baseKey: string,
  value: string,
  scope?: string,
): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(buildTenantScopedStorageKey(baseKey, scope), value)
  } catch {
    /* quota / private mode */
  }
}

export function removeTenantScopedStorageItem(baseKey: string, scope?: string): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.removeItem(buildTenantScopedStorageKey(baseKey, scope))
  } catch {
    /* ignore */
  }
}

/** 写入 chat / mod 等复合 key 时的租户前缀段（local 域为空串）。 */
export function tenantScopedKeySegment(scope?: string): string {
  const s = scope || resolveTenantStorageScopeFromRuntime()
  return s === 'local' ? '' : `${s}:`
}

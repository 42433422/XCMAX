import { readActiveExtensionModIdFromStorage, XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY } from '@/utils/xcagiStorageKeys'
import { resolveTenantStorageScopeFromRuntime, tenantScopedKeySegment } from '@/utils/tenantStorageScope'
import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'

export const CHAT_MESSAGES_STORAGE_PREFIX = 'xcagi_chat_messages_'
export const CHAT_SESSION_META_PREFIX = 'xcagi_chat_session_meta_'

/** Chat state belongs to an authenticated owner, tenant and active Mod. */
export function readActiveModIdFromStorage(scope?: string): string {
  return readActiveExtensionModIdFromStorage(scope)
}

function scopedSuffix(sessionId: string, modId: string, scope?: string): string {
  const tenantPart = tenantScopedKeySegment(scope || resolveChatStorageScope())
  const sid = String(sessionId || 'default')
  return modId ? `${tenantPart}mod:${modId}:${sid}` : `${tenantPart}${sid}`
}

export function resolveChatStorageScope(): string {
  const identity = getRuntimeTenantStorageScopeInput()
  const tenant = resolveTenantStorageScopeFromRuntime(true)
  const owner = identity?.localUserId ?? identity?.marketUserId ?? identity?.marketUsername
  return tenant.startsWith('tenant:') && owner != null && String(owner).trim()
    ? `${tenant}:owner:${encodeURIComponent(String(owner))}` : tenant
}

export function resolveChatIdentity(modId = readActiveModIdFromStorage()): string {
  return JSON.stringify([resolveChatStorageScope(), modId])
}

export function buildChatMessagesKey(sessionId: string, modId?: string, scope?: string): string {
  return buildChatScopedKey(CHAT_MESSAGES_STORAGE_PREFIX, sessionId, modId, scope)
}

export function buildChatSessionMetaKey(sessionId: string, modId?: string, scope?: string): string {
  return buildChatScopedKey(CHAT_SESSION_META_PREFIX, sessionId, modId, scope)
}

export function buildChatScopedKey(prefix: string, sessionId: string, modId?: string, scope?: string): string {
  const mod = typeof modId === 'string' ? modId : readActiveModIdFromStorage(scope)
  return `${prefix}${scopedSuffix(sessionId, mod, scope)}`
}

function stripTenantSegment(suffix: string, scope?: string): string | null {
  const s = scope || resolveChatStorageScope()
  if (s === 'local') return /^(?:tenant|user|session|platform):/.test(suffix) ? null : suffix
  const needle = `${s}:`
  if (!suffix.startsWith(needle)) return null
  return suffix.slice(needle.length)
}

/**
 * 从 localStorage 原始 key 中识别出属于当前租户 + Mod 的 sessionId。
 */
export function extractSessionIdForActiveMod(prefix: string, key: string, activeModId?: string, scope?: string): string | null {
  const raw = String(key || '')
  if (!raw.startsWith(prefix)) return null
  const scoped = stripTenantSegment(raw.slice(prefix.length), scope)
  if (scoped == null) return null
  const mod = typeof activeModId === 'string' ? activeModId : readActiveModIdFromStorage(scope)
  if (mod) {
    const needle = `mod:${mod}:`
    if (!scoped.startsWith(needle)) return null
    const sid = scoped.slice(needle.length)
    return sid || null
  }
  if (scoped.startsWith('mod:')) return null
  return scoped || null
}

/** 供 lint/文档引用：租户隔离后的 Mod 选择 key 基名 */
export { XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY }

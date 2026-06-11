import {
  readActiveExtensionModIdFromStorage,
  XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY,
} from '@/utils/xcagiStorageKeys'
import {
  resolveTenantStorageScopeFromRuntime,
  tenantScopedKeySegment,
} from '@/utils/tenantStorageScope'

export const CHAT_MESSAGES_STORAGE_PREFIX = 'xcagi_chat_messages_'
export const CHAT_SESSION_META_PREFIX = 'xcagi_chat_session_meta_'

/**
 * 聊天记录按 **租户 + 扩展（Mod）** 隔离。
 *
 * - 有租户且有 Mod：``xcagi_chat_messages_tenant:42:mod:<modId>:<sessionId>``
 * - 有租户无 Mod：``xcagi_chat_messages_tenant:42:<sessionId>``
 * - 未绑定租户（local 域）时与旧版格式兼容。
 */
export function readActiveModIdFromStorage(): string {
  return readActiveExtensionModIdFromStorage()
}

function scopedSuffix(sessionId: string, modId: string, scope?: string): string {
  const tenantPart = tenantScopedKeySegment(scope)
  const sid = String(sessionId || 'default')
  return modId ? `${tenantPart}mod:${modId}:${sid}` : `${tenantPart}${sid}`
}

export function buildChatMessagesKey(sessionId: string, modId?: string, scope?: string): string {
  const mod = typeof modId === 'string' ? modId : readActiveModIdFromStorage(scope)
  return `${CHAT_MESSAGES_STORAGE_PREFIX}${scopedSuffix(sessionId, mod, scope)}`
}

export function buildChatSessionMetaKey(sessionId: string, modId?: string, scope?: string): string {
  const mod = typeof modId === 'string' ? modId : readActiveModIdFromStorage(scope)
  return `${CHAT_SESSION_META_PREFIX}${scopedSuffix(sessionId, mod, scope)}`
}

function stripTenantSegment(suffix: string, scope?: string): string | null {
  const s = scope || resolveTenantStorageScopeFromRuntime()
  if (s === 'local') return suffix
  const needle = `${s}:`
  if (!suffix.startsWith(needle)) return null
  return suffix.slice(needle.length)
}

/**
 * 从 localStorage 原始 key 中识别出属于当前租户 + Mod 的 sessionId。
 */
export function extractSessionIdForActiveMod(
  prefix: string,
  key: string,
  activeModId?: string,
  scope?: string,
): string | null {
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

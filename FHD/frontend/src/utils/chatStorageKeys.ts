import { XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY } from '@/utils/xcagiStorageKeys'

export const CHAT_MESSAGES_STORAGE_PREFIX = 'xcagi_chat_messages_'
export const CHAT_SESSION_META_PREFIX = 'xcagi_chat_session_meta_'

/**
 * 聊天记录按扩展（Mod）隔离。
 *
 * - 已选中 Mod 时，key 形如 ``xcagi_chat_messages_mod:<modId>:<sessionId>``；
 * - 未选中 Mod（"原版模式"）时，沿用旧格式 ``xcagi_chat_messages_<sessionId>``，
 *   以便升级后老会话仍可复用。
 */
export function readActiveModIdFromStorage(): string {
  try {
    return String(localStorage.getItem(XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY) || '').trim()
  } catch {
    return ''
  }
}

function scopedSuffix(sessionId: string, modId: string): string {
  const sid = String(sessionId || 'default')
  return modId ? `mod:${modId}:${sid}` : sid
}

export function buildChatMessagesKey(sessionId: string, modId?: string): string {
  const mod = typeof modId === 'string' ? modId : readActiveModIdFromStorage()
  return `${CHAT_MESSAGES_STORAGE_PREFIX}${scopedSuffix(sessionId, mod)}`
}

export function buildChatSessionMetaKey(sessionId: string, modId?: string): string {
  const mod = typeof modId === 'string' ? modId : readActiveModIdFromStorage()
  return `${CHAT_SESSION_META_PREFIX}${scopedSuffix(sessionId, mod)}`
}

/**
 * 从 localStorage 原始 key 中识别出属于当前 Mod 的 sessionId。
 * - 当前有 Mod：严格匹配 ``${prefix}mod:<currentMod>:<sid>``；
 * - 当前无 Mod（原版）：匹配 ``${prefix}<sid>`` 且后缀不以 ``mod:`` 开头。
 *
 * 匹配失败返回 ``null``，便于调用方过滤跨 Mod 残留的旧 key。
 */
export function extractSessionIdForActiveMod(prefix: string, key: string, activeModId?: string): string | null {
  const raw = String(key || '')
  if (!raw.startsWith(prefix)) return null
  const suffix = raw.slice(prefix.length)
  const mod = typeof activeModId === 'string' ? activeModId : readActiveModIdFromStorage()
  if (mod) {
    const needle = `mod:${mod}:`
    if (!suffix.startsWith(needle)) return null
    const sid = suffix.slice(needle.length)
    return sid || null
  }
  if (suffix.startsWith('mod:')) return null
  return suffix || null
}

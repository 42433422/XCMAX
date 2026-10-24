import {
  readTenantScopedStorageItem,
  removeTenantScopedStorageItem,
  writeTenantScopedStorageItem,
} from '@/utils/tenantStorageScope'

/** 当前会话只启用哪一个扩展包（与 apiFetch 请求头、mods store 一致） */
export const XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY = 'xcagi_active_extension_mod_id'

/** 开发者模式：为 true 时请求头尝试 P2（仍须 elevated token 与服务器一致） */
export const XCAGI_AI_DEVELOPER_MODE_KEY = 'xcagi_ai_developer_mode'

/** 与服务器 FHD_AI_ELEVATED_TOKEN 相同的口令（仅存本机 localStorage） */
export const XCAGI_AI_ELEVATED_TOKEN_KEY = 'xcagi_ai_elevated_token'

/** 设置页保存后派发，便于智脑等同页刷新 P1/P2 展示（storage 事件不跨同标签页） */
export const XCAGI_AI_TIER_CHANGED_EVENT = 'xcagi-ai-tier-changed'

export function readActiveExtensionModIdFromStorage(scope?: string): string {
  return String(readTenantScopedStorageItem(XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY, scope) || '').trim()
}

export function writeActiveExtensionModIdToStorage(modId: string | null | undefined, scope?: string): void {
  const next = String(modId || '').trim()
  if (next) writeTenantScopedStorageItem(XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY, next, scope)
  else removeTenantScopedStorageItem(XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY, scope)
}

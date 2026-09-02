/**
 * mods store 共享类型与纯函数（拆分自 stores/mods.ts，行为保持一致）。
 */
import type { ModInfo } from '@/types/modInfo'
import { readActiveExtensionModIdFromStorage } from '@/utils/xcagiStorageKeys'

export type FetchModsOptions = {
  /** 为 true 时只更新 mods 列表，不再调用 applyEntitledActiveMod（打破递归） */
  skipEntitledApply?: boolean
}

export type ModsInitializeOptions = {
  entitledModIds?: string[]
  /** 登录后按账号权益强制选 Mod（覆盖 localStorage 中的旧扩展） */
  forceFromEntitlements?: boolean
  /** 本机登录名（仅用于本地演示账号兜底；正式账号由服务端 entitlement 驱动） */
  accountUsername?: string
}

/**
 * 仅前端「原版模式」：不展示 Mod、不请求 /api/mods*、不注册 Mod 路由、不保留 Mod 内存状态。
 * 与后端 XCAGI_DISABLE_MODS 无关；重新打开需刷新页面。
 */
export const CLIENT_MODS_UI_OFF_KEY = 'xcagi_client_mods_ui_off'

export interface ModRoute {
  mod_id: string
  routes_path: string
}

export function readClientModsUiOff(): boolean {
  try {
    return localStorage.getItem(CLIENT_MODS_UI_OFF_KEY) === '1'
  } catch {
    return false
  }
}

export function readActiveModId(scope?: string): string {
  try {
    return readActiveExtensionModIdFromStorage(scope)
  } catch {
    return ''
  }
}

export function delay(ms: number) {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, ms)
  })
}

/** 与后端当前行业对齐：从若干 manifest 中选一个扩展包 */
export function pickModMatchingIndustry(list: ModInfo[], industryId: string, preferredModId: string): ModInfo | null {
  const sid = String(industryId || '').trim()
  if (!sid || !list.length) return null
  const candidates = list.filter((m) => String(m.industry?.id || '').trim() === sid)
  if (!candidates.length) return null
  const pref = String(preferredModId || '').trim()
  const prefHit = candidates.find((m) => String(m.id || '').trim() === pref)
  if (prefHit) return prefHit
  const primary = candidates.find((m) => m.primary === true)
  if (primary) return primary
  return candidates[0]
}

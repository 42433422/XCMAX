/** sessionStorage：未设置时默认开启平台模式（纯聊天，隐藏做 Mod/做员工） */
export const WB_PLATFORM_CHAT_MODE_KEY = 'wb_platform_chat_mode_v2'
const WB_PLATFORM_CHAT_MODE_LEGACY_KEY = 'wb_platform_chat_mode'

/** `null` → 默认开；`'1'` → 开；`'0'` → 用户明确关闭 */
export function readPlatformChatModePreference(): boolean {
  try {
    const v = sessionStorage.getItem(WB_PLATFORM_CHAT_MODE_KEY)
    if (v !== null) return v === '1'
    const legacy = sessionStorage.getItem(WB_PLATFORM_CHAT_MODE_LEGACY_KEY)
    if (legacy === '1') {
      writePlatformChatModePreference(true)
      return true
    }
    // 旧版默认关，且切到「聊」会误写 '0'，无法区分 → 迁移为默认开
    if (legacy === '0') {
      writePlatformChatModePreference(true)
      return true
    }
    return true
  } catch {
    return true
  }
}

export function writePlatformChatModePreference(on: boolean): void {
  try {
    sessionStorage.setItem(WB_PLATFORM_CHAT_MODE_KEY, on ? '1' : '0')
  } catch {
    /* ignore */
  }
}

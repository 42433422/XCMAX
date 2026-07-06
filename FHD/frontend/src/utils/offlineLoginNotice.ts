/** 离线登录提示：登录响应带 offline_login=true 时写入，主布局展示一次性横幅 */

const KEY = 'xcagi_offline_login_notice'

export const DEFAULT_OFFLINE_LOGIN_NOTICE =
  '市场服务暂时不可达，已使用本机账号离线登录；商店与权益同步等在线功能恢复联网后自动可用。'

export function rememberOfflineLoginNotice(message?: string): void {
  try {
    sessionStorage.setItem(KEY, (message || '').trim() || DEFAULT_OFFLINE_LOGIN_NOTICE)
  } catch {
    /* ignore */
  }
}

export function readOfflineLoginNotice(): string {
  try {
    return sessionStorage.getItem(KEY) || ''
  } catch {
    return ''
  }
}

export function clearOfflineLoginNotice(): void {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}

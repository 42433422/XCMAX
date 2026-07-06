/** 桌面更新「上次检查时间」：设置-关于与桌面运行时页共用 */

const KEY = 'xcagi_desktop_update_last_check'

export function rememberUpdateCheckTime(): string {
  const iso = new Date().toISOString()
  try {
    localStorage.setItem(KEY, iso)
  } catch {
    /* ignore */
  }
  return iso
}

export function readUpdateCheckTime(): string {
  try {
    return localStorage.getItem(KEY) || ''
  } catch {
    return ''
  }
}

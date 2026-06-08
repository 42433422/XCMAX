/** 是否运行在 XCAGI 桌面 Electron 壳内（含 preload 注入的 xcagiDesktop）。 */
export function isDesktopShell(): boolean {
  if (typeof window === 'undefined') return false
  if ((window as Window & { xcagiDesktop?: unknown }).xcagiDesktop) return true
  return typeof navigator !== 'undefined' && /Electron/i.test(navigator.userAgent)
}

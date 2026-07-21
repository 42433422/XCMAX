/** 是否运行在 XCAGI 桌面 Electron 壳内（仅认 preload 注入的 xcagiDesktop）。

勿用 User-Agent 匹配 `/Electron/`：Cursor / VS Code 内置浏览器也是 Electron，
会把网页管理端误判成桌面壳，从而拒登 admin。
*/
export function isDesktopShell(): boolean {
  if (typeof window === 'undefined') return false
  return Boolean((window as Window & { xcagiDesktop?: unknown }).xcagiDesktop)
}

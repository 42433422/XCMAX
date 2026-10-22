import { isTrustedDesktopOrigin } from './desktop-navigation'

/**
 * IPC 逐 handler 来源校验（2026-09-05 审计 R02 整改）。
 *
 * 桌面端 preload 暴露的通道包含密钥读写、剪贴板、原生路径打开与更新安装等
 * 高权限能力。窗口虽已开启 contextIsolation/sandbox 且禁用 Node integration，
 * 但 Electron 默认允许任意 frame（含被注入的 iframe、导航后的页面）调用
 * ipcMain.handle 通道。本守卫把「谁能调用」收敛为：
 *
 * 1. 仅主窗口 webContents（拒绝其他窗口/隐藏视图）；
 * 2. 仅主框架（拒绝子 frame/iframe）；
 * 3. 仅配置端口的业务来源，或主进程选定的唯一 splash 文件，
 *    导航到外部站点后的调用一律拒绝。
 */

export interface TrustedIpcPolicy {
  port: number
  splashUrl: string
}

export interface TrustedSenderWindow {
  isDestroyed(): boolean
  webContents: { id: number; mainFrame: unknown }
}

/** 只依赖实际读取的字段，避免耦合 Electron 完整类型（也便于单测注入）。 */
export interface IpcSenderProbe {
  sender: { id: number }
  senderFrame: { url?: string } | null | undefined
}

export function isTrustedIpcSender(
  event: IpcSenderProbe,
  mainWindow: TrustedSenderWindow | null | undefined,
  policy: TrustedIpcPolicy,
): boolean {
  if (!mainWindow || mainWindow.isDestroyed()) return false
  // 只认主窗口（当前应用没有第二台受信窗口；弹窗/其他 webContents 一律拒绝）。
  if (event.sender.id !== mainWindow.webContents.id) return false
  // 拒绝子 frame：senderFrame 必须存在且就是主框架（导航后 URL 变化由下面校验兜底）。
  if (!event.senderFrame || event.senderFrame !== mainWindow.webContents.mainFrame) return false
  const frameUrl = String((event.senderFrame as { url?: string }).url || '')
  let parsed: URL
  try {
    parsed = new URL(frameUrl)
  } catch {
    return false
  }
  if (parsed.protocol === 'file:') {
    try {
      const splash = new URL(policy.splashUrl)
      return splash.protocol === 'file:' && parsed.href === splash.href
    } catch {
      return false
    }
  }
  return isTrustedDesktopOrigin(frameUrl, policy.port)
}

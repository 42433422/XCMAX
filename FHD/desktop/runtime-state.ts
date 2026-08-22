import type { BrowserWindow, Tray } from 'electron'
import type { ChildProcessWithoutNullStreams } from 'node:child_process'
import type fs from 'node:fs'
import type { AutonomyController } from './autonomy/controller'

export type DesktopStartupMarks = {
  backendSpawnMs?: number
  backendHealthMs?: number
  desktopStatusMs?: number
}

/**
 * 跨模块共享的桌面运行时状态（单例）。
 * main.ts 拆分后，窗口/后端进程/托盘/自治控制器等可变引用统一收敛到这里，
 * 各模块只读写本对象，禁止把可变状态回流到 main.ts 或散落到各自模块级变量。
 */
export const desktopRuntime = {
  mainWindow: null as BrowserWindow | null,
  backendProcess: null as ChildProcessWithoutNullStreams | null,
  backendLogStream: null as fs.WriteStream | null,
  tray: null as Tray | null,
  restartCount: 0,
  backendShutdownComplete: false,
  backendShutdownPromise: null as Promise<void> | null,
  rendererFailedDuringStartup: false,
  mainApplicationReady: null as Promise<void> | null,
  // 一次性、渲染端可见的登录态提示，仅来自本地 Chromium cookie；
  // 不授权任何 API 请求，消费后即清除（见 ipc-handlers consume-bootstrap-session-hint）。
  desktopBootstrapSessionHintAvailable: false,
  // 深链（xcagi://）：pending 供渲染端在启动后一次性拉取，也通过事件推送实时路径。
  pendingDeepLink: null as string | null,
  autonomyController: null as AutonomyController | null,
  startupMarks: {} as DesktopStartupMarks,
}

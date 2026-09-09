import { Notification, app, clipboard, ipcMain, shell } from 'electron'
import type { IpcMainInvokeEvent } from 'electron'
import crypto from 'node:crypto'
import fs from 'node:fs'
import { networkInterfaces } from 'node:os'
import { APP_NAME, DEFAULT_PORT, readPackagedAppVersion } from './desktop-config'
import { desktopRuntime } from './runtime-state'
import { isTrustedIpcSender } from './ipc-sender-guard'
import { broadcastToRenderer } from './window-manager'
import { runBackendMigrationWithRollback, stopBackend, writeBackendLog } from './backend-process'
import {
  captureFullScreenScreenshot,
  consumeReleaseNotes,
  exportSupportBundleInteractive,
  getAutoLaunchEnabled,
  openKellaiDesktop,
  setAutoLaunchEnabled,
} from './app-shell'
import {
  downloadUpdate,
  getUpdateStatus,
  runUpdateCheckWithDirectNet,
} from './updater'
import { cancelPreparedRollback } from './rollback'
import { assertSelfUpdateInstallSupported, getDesktopInstallIdentity, installUpdate } from './desktop-install-update'
import { desktopOfflineDbPath, queryOffline } from './data-bridge'
import { deleteSecret, getSecret, listSecrets, setSecret } from './secure-store'
import { reportRendererError } from './desktop-resilience'

function getLanIPv4(): string {
  const nets = networkInterfaces()
  for (const name of Object.keys(nets)) {
    for (const iface of nets[name] || []) {
      if (iface.family === 'IPv4' && !iface.internal) {
        return iface.address
      }
    }
  }
  return '127.0.0.1'
}

/**
 * 审计 R02 整改：所有 ipcMain.handle 通道统一经来源校验后再执行。
 * 拒绝非主窗口、子 frame 与导航后外部来源的调用；密钥/剪贴板/路径打开/
 * 更新安装等高权限 handler 不再无条件信任任意 webContents。
 */
function handleTrusted<T extends unknown[]>(
  channel: string,
  handler: (event: IpcMainInvokeEvent, ...args: T) => unknown,
): void {
  ipcMain.handle(channel, (event: IpcMainInvokeEvent, ...args: unknown[]) => {
    if (!isTrustedIpcSender(event, desktopRuntime.mainWindow)) {
      writeBackendLog(`[ipc] rejected call from untrusted sender channel=${channel}\n`)
      return { ok: false, reason: 'untrusted_sender' }
    }
    return handler(event, ...(args as T))
  })
}

/**
 * 注册渲染端可见的全部 IPC handler（preload.ts 的 xcagiDesktop 一一对应）。
 * 仅在 app.whenReady 之后调用一次。
 */
export function registerDesktopIpcHandlers(): void {
  handleTrusted('xcagi:pairing-qr', async () => {
    const host = getLanIPv4()
    const port = DEFAULT_PORT
    const nonce = crypto.randomBytes(12).toString('base64url')
    const exp = Math.floor(Date.now() / 1000) + 300
    try {
      const res = await fetch(`http://127.0.0.1:${port}/api/mobile/v1/pairing/issue`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ host, port })
      })
      if (res.ok) {
        const json = (await res.json()) as { data?: { nonce?: string; exp?: number; host?: string; port?: number } }
        if (json?.data?.nonce) {
          return JSON.stringify(json.data)
        }
      }
    } catch {
      /* backend offline — return local payload */
    }
    return JSON.stringify({ host, port, nonce, exp })
  })

  handleTrusted('xcagi:get-data-dir', () => app.getPath('userData'))
  handleTrusted('xcagi:consume-bootstrap-session-hint', () => {
    const available = desktopRuntime.desktopBootstrapSessionHintAvailable
    desktopRuntime.desktopBootstrapSessionHintAvailable = false
    return available
  })
  handleTrusted('xcagi:get-app-identity', () => ({
    name: app.getName(),
    version: readPackagedAppVersion(),
    isPackaged: app.isPackaged,
    install: getDesktopInstallIdentity(),
  }))
  handleTrusted('xcagi:open-kellai-desktop', () => openKellaiDesktop())
  handleTrusted('xcagi:export-support-bundle', () => exportSupportBundleInteractive())
  handleTrusted('xcagi:check-for-updates', () => runUpdateCheckWithDirectNet())
  handleTrusted('xcagi:get-update-status', () => getUpdateStatus())
  handleTrusted('xcagi:download-update', () => {
    assertSelfUpdateInstallSupported()
    return downloadUpdate()
  })
  handleTrusted('xcagi:install-update', () => {
    assertSelfUpdateInstallSupported()
    // prepareQuit：quitAndInstall 前先同步停掉后端，确保 macOS 原生 terminate 路径下应用能真正退出
    return installUpdate(runBackendMigrationWithRollback, cancelPreparedRollback, stopBackend)
  })
  handleTrusted('xcagi:set-badge', (_event, count: number) => {
    const n = Math.max(0, Math.floor(Number(count) || 0))
    if (process.platform === 'darwin' || process.platform === 'linux') {
      app.setBadgeCount(n)
      return
    }
    const mainWindow = desktopRuntime.mainWindow
    if (mainWindow) {
      mainWindow.flashFrame(n > 0)
    }
  })
  ipcMain.handle(
    'xcagi:show-notification',
    (_event, payload: { title?: string; body?: string }) => {
      const title = String(payload?.title || APP_NAME).trim() || APP_NAME
      const body = String(payload?.body || '').trim()
      if (!Notification.isSupported()) {
        return { ok: false, reason: 'unsupported' }
      }
      const notification = new Notification({ title, body })
      notification.on('click', () => {
        const mainWindow = desktopRuntime.mainWindow
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.show()
          mainWindow.focus()
        }
      })
      notification.show()
      return { ok: true }
    }
  )

  // 原生本地数据桥（离线只读）：后端 HTTP 不可用时前端可直读本地 SQLite。
  handleTrusted('xcagi:offline-query', (_event, params: unknown) => {
    const p = (params && typeof params === 'object' ? params : {}) as {
      kind?: string
      keyword?: string
      limit?: number
    }
    return queryOffline(desktopOfflineDbPath(), {
      kind: String(p.kind || ''),
      keyword: p.keyword,
      limit: p.limit,
    })
  })

  // 端侧密钥链（safeStorage）：敏感配置加密落盘，明文只驻内存。
  handleTrusted('xcagi:secure-get', (_event, key: string) => getSecret(String(key)))
  handleTrusted('xcagi:secure-set', (_event, key: string, value: string) =>
    setSecret(String(key), value === undefined ? '' : String(value)),
  )
  handleTrusted('xcagi:secure-delete', (_event, key: string) => deleteSecret(String(key)))
  handleTrusted('xcagi:secure-list', () => listSecrets())

  // 剪贴板原生读写（P2 高频微交互）。
  handleTrusted('xcagi:clipboard-read-text', () => clipboard.readText())
  handleTrusted('xcagi:clipboard-write-text', (_event, text: string) => {
    clipboard.writeText(String(text ?? ''))
    return { ok: true }
  })
  // 原生打开本地路径（文件/目录），供拖拽文件、导出等场景系统级打开。
  handleTrusted('xcagi:open-path', async (_event, target: string) => {
    const p = String(target || '')
    if (!p || !fs.existsSync(p)) return { ok: false, reason: 'not_found' }
    const err = await shell.openPath(p)
    return { ok: !err, reason: err || undefined }
  })

  // 开机自启开关。
  handleTrusted('xcagi:get-auto-launch', () => getAutoLaunchEnabled())
  handleTrusted('xcagi:set-auto-launch', (_event, enabled: boolean) =>
    setAutoLaunchEnabled(Boolean(enabled)),
  )

  // 深链：渲染端启动后可一次性拉取在窗口就绪前到达的唤起。
  handleTrusted('xcagi:consume-deep-link', () => {
    const url = desktopRuntime.pendingDeepLink
    desktopRuntime.pendingDeepLink = null
    return url
  })

  // 渲染进程错误遥测：复用后端 crash-report 通道（opt-in 由后端统一聚合），best-effort。
  handleTrusted(
    'xcagi:report-error',
    (_event, payload: { type?: string; error?: string; stack?: string }) => {
      const p = payload && typeof payload === 'object' ? payload : {}
      reportRendererError(
        { port: DEFAULT_PORT, writeLog: writeBackendLog },
        {
          type: String(p.type || 'renderer:error'),
          error: String(p.error || 'unknown'),
          stack: typeof p.stack === 'string' ? p.stack : undefined,
        },
      )
    },
  )

  // 首次引导 + 更新日志。
  handleTrusted('xcagi:consume-release-notes', () => consumeReleaseNotes())

  // 全局截图（渲染端主动触发 / 快捷键触发共用）。
  handleTrusted('xcagi:capture-screenshot', async () => {
    const result = await captureFullScreenScreenshot()
    broadcastToRenderer('xcagi:screenshot-captured', result)
    return result
  })
}

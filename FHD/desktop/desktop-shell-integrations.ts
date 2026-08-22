import { app, clipboard, desktopCapturer, dialog, globalShortcut, ipcMain, screen, type BrowserWindow } from 'electron'
import fs from 'node:fs'
import path from 'node:path'
import { parseDesktopDeepLink, findDeepLinkArg } from './desktop-navigation'
import { reportRendererError } from './desktop-resilience'
import { readLocalProductVersion } from './updater'

const RELEASE_NOTES: Record<string, string> = {
  '1.0.0.1':
    '· 桌面端新增：开机自启、xcagi:// 深链唤起、渲染错误遥测、全局截图与语音唤起快捷键\n' + '· 继续保持更新观察期自动回滚与稳定性保障',
}

export interface DesktopShellIntegrationOptions {
  appName: string
  backendPort: number
  getMainWindow: () => BrowserWindow | null
  toggleMainWindow: () => void
  writeLog: (line: string) => void
}

function desktopSettingsPath(): string {
  return path.join(app.getPath('userData'), 'desktop-settings.json')
}

function readDesktopSettings(): Record<string, unknown> {
  try {
    const parsed = JSON.parse(fs.readFileSync(desktopSettingsPath(), 'utf8'))
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

function patchDesktopSettings(patch: Record<string, unknown>): void {
  try {
    fs.writeFileSync(desktopSettingsPath(), JSON.stringify({ ...readDesktopSettings(), ...patch }, null, 2), 'utf8')
  } catch {
    /* 设置落盘失败不阻塞启动 */
  }
}

export function getAutoLaunchEnabled(): boolean {
  try {
    return app.getLoginItemSettings().openAtLogin
  } catch {
    return false
  }
}

export function setAutoLaunchEnabled(enabled: boolean): { ok: boolean; reason?: string } {
  try {
    app.setLoginItemSettings({ openAtLogin: enabled })
    return { ok: true }
  } catch (error) {
    return { ok: false, reason: error instanceof Error ? error.message : String(error) }
  }
}

function releaseNoteStatePath(): string {
  return path.join(app.getPath('userData'), 'release-note-state.json')
}

export function consumeReleaseNotes(): {
  isFirstRun: boolean
  fromVersion: string | null
  toVersion: string
  notes: string
} | null {
  const toVersion = readLocalProductVersion()
  let lastSeen: string | null = null
  try {
    const raw = JSON.parse(fs.readFileSync(releaseNoteStatePath(), 'utf8'))
    if (typeof raw?.version === 'string') lastSeen = raw.version
  } catch {
    /* 首次运行或损坏状态，等同首次 */
  }
  if (lastSeen === toVersion) return null
  const isFirstRun = lastSeen === null
  const notes = RELEASE_NOTES[toVersion] ?? `已更新到 v${toVersion}。`
  try {
    fs.writeFileSync(releaseNoteStatePath(), JSON.stringify({ version: toVersion, seenAt: new Date().toISOString() }), 'utf8')
  } catch {
    /* 忽略记录失败 */
  }
  return { isFirstRun, fromVersion: lastSeen, toVersion, notes }
}

function screenshotOutputDir(): string {
  const dir = path.join(app.getPath('userData'), 'captures')
  fs.mkdirSync(dir, { recursive: true })
  return dir
}

export async function captureFullScreenScreenshot(): Promise<{
  ok: boolean
  path?: string
  error?: string
}> {
  try {
    if (!desktopCapturer?.getSources) return { ok: false, error: 'desktopCapturer unavailable' }
    const primary = screen.getPrimaryDisplay()
    const sources = await desktopCapturer.getSources({
      types: ['screen'],
      thumbnailSize: { width: primary.size.width, height: primary.size.height },
    })
    const source = sources.find((item) => item.display_id === String(primary.id)) || sources[0]
    if (!source || source.thumbnail.isEmpty()) return { ok: false, error: 'no screenshot source' }
    const image = source.thumbnail
    clipboard.writeImage(image)
    const outPath = path.join(screenshotOutputDir(), `screenshot-${Date.now()}.png`)
    fs.writeFileSync(outPath, image.toPNG())
    return { ok: true, path: outPath }
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) }
  }
}

export function createDesktopShellIntegrations(options: DesktopShellIntegrationOptions) {
  let pendingDeepLink: string | null = null

  const broadcast = (channel: string, payload?: unknown): void => {
    const window = options.getMainWindow()
    if (window && !window.isDestroyed() && !window.webContents.isLoading()) {
      window.webContents.send(channel, payload)
    }
  }

  const handleDeepLink = (rawUrl: string): void => {
    const parsed = parseDesktopDeepLink(rawUrl)
    if (!parsed) return
    pendingDeepLink = parsed.raw
    options.writeLog(`[deeplink] received host=${parsed.host} path=${parsed.path}\n`)
    const window = options.getMainWindow()
    if (window && !window.isDestroyed()) {
      window.show()
      if (window.isMinimized()) window.restore()
      window.focus()
      broadcast('xcagi:deep-link', parsed.raw)
    }
  }

  return {
    registerProtocolHandlers(): void {
      app.on('open-url', (event, rawUrl) => {
        event.preventDefault()
        if (rawUrl?.startsWith('xcagi://')) handleDeepLink(rawUrl)
      })
    },

    handleSecondInstance(commandLine: string[]): void {
      const deepLink = findDeepLinkArg(commandLine)
      if (deepLink) handleDeepLink(deepLink)
      const window = options.getMainWindow()
      if (window && !window.isDestroyed()) {
        if (window.isMinimized()) window.restore()
        window.show()
        window.focus()
      }
    },

    initialize(): void {
      try {
        app.setAsDefaultProtocolClient('xcagi')
      } catch {
        /* 深链注册失败仅降低对外唤起能力 */
      }
      if (!readDesktopSettings().autoLaunchInitialized) {
        const init = setAutoLaunchEnabled(true)
        patchDesktopSettings({ autoLaunchInitialized: true })
        if (!init.ok) options.writeLog(`[autolaunch] initial enable failed: ${init.reason}\n`)
      }

      ipcMain.handle('xcagi:get-auto-launch', () => getAutoLaunchEnabled())
      ipcMain.handle('xcagi:set-auto-launch', (_event, enabled: boolean) => setAutoLaunchEnabled(Boolean(enabled)))
      ipcMain.handle('xcagi:consume-deep-link', () => {
        const url = pendingDeepLink
        pendingDeepLink = null
        return url
      })
      ipcMain.handle('xcagi:report-error', (_event, payload: { type?: string; error?: string; stack?: string }) => {
        const value = payload && typeof payload === 'object' ? payload : {}
        reportRendererError(
          { port: options.backendPort, writeLog: options.writeLog },
          {
            type: String(value.type || 'renderer:error'),
            error: String(value.error || 'unknown'),
            stack: typeof value.stack === 'string' ? value.stack : undefined,
          },
        )
      })
      ipcMain.handle('xcagi:consume-release-notes', () => consumeReleaseNotes())
      ipcMain.handle('xcagi:capture-screenshot', async () => {
        const result = await captureFullScreenScreenshot()
        broadcast('xcagi:screenshot-captured', result)
        return result
      })

      try {
        globalShortcut.register('CommandOrControl+Shift+X', options.toggleMainWindow)
      } catch {
        /* 全局快捷键注册失败不阻塞启动 */
      }
      try {
        globalShortcut.register('CommandOrControl+Shift+5', () => {
          void captureFullScreenScreenshot().then((result) => {
            broadcast('xcagi:screenshot-captured', result)
            if (result.ok) options.writeLog(`[capture] saved ${result.path}\n`)
          })
        })
      } catch {
        /* 全局快捷键注册失败不阻塞启动 */
      }
      try {
        globalShortcut.register('CommandOrControl+Shift+V', () => {
          options.toggleMainWindow()
          broadcast('xcagi:voice-invoke')
        })
      } catch {
        /* 全局快捷键注册失败不阻塞启动 */
      }
    },

    showReleaseNotes(): void {
      if (process.env.XCAGI_DESKTOP_TEST) return
      const releaseNote = consumeReleaseNotes()
      if (!releaseNote || releaseNote.isFirstRun) return
      const fromText = releaseNote.fromVersion ? `（${releaseNote.fromVersion} → ${releaseNote.toVersion}）` : ''
      const messageBoxOptions: Electron.MessageBoxOptions = {
        type: 'info',
        title: `${options.appName} 已更新${fromText}`,
        message: `XCAGI 已更新到 v${releaseNote.toVersion}`,
        detail: releaseNote.notes,
        buttons: ['知道了'],
        defaultId: 0,
      }
      const window = options.getMainWindow()
      if (window && !window.isDestroyed()) {
        void dialog.showMessageBox(window, messageBoxOptions)
      } else {
        void dialog.showMessageBox(messageBoxOptions)
      }
    },
  }
}

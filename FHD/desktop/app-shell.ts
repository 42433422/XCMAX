import {
  BrowserWindow,
  Menu,
  Tray,
  app,
  clipboard,
  desktopCapturer,
  dialog,
  nativeImage,
  screen,
  session,
  shell,
} from 'electron'
import { execFile } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { APP_NAME, DEFAULT_PORT, shellIconPath } from './desktop-config'
import { desktopRuntime } from './runtime-state'
import { broadcastToRenderer, toggleMainWindow } from './window-manager'
import { writeBackendLog } from './backend-process'
import { readLocalProductVersion, runUpdateCheckWithDirectNet } from './updater'
import { parseDesktopDeepLink } from './desktop-navigation'

const KELLAI_BUNDLE_ID = 'com.kellai.desktop'

// ---------- 设置持久化（开机自启初始化标记 / 遥测开关等） ----------
function desktopSettingsPath(): string {
  return path.join(app.getPath('userData'), 'desktop-settings.json')
}
export function readDesktopSettings(): Record<string, unknown> {
  try {
    const raw = fs.readFileSync(desktopSettingsPath(), 'utf8')
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}
export function patchDesktopSettings(patch: Record<string, unknown>): void {
  try {
    const prev = readDesktopSettings()
    fs.writeFileSync(desktopSettingsPath(), JSON.stringify({ ...prev, ...patch }, null, 2), 'utf8')
  } catch {
    /* 设置落盘失败不阻塞启动 */
  }
}

// ---------- 开机自启 ----------
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

// ---------- 首次引导 + 更新日志（What's New） ----------
const RELEASE_NOTES: Record<string, string> = {
  '1.0.0.1':
    '· 桌面端新增：开机自启、xcagi:// 深链唤起、渲染错误遥测、全局截图与语音唤起快捷键\n' +
    '· 继续保持更新观察期自动回滚与稳定性保障',
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
    fs.writeFileSync(
      releaseNoteStatePath(),
      JSON.stringify({ version: toVersion, seenAt: new Date().toISOString() }),
      'utf8',
    )
  } catch {
    /* 忽略记录失败 */
  }
  return { isFirstRun, fromVersion: lastSeen, toVersion, notes }
}

// ---------- 全局截图 / 语音唤起 ----------
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
    const source = sources.find(s => s.display_id === String(primary.id)) || sources[0]
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

/**
 * 深链入口：同时处理 second-instance argv（win/linux）与 mac open-url。
 * 唤起窗口 + 逻辑置为 pending，若渲染端已就绪则实时推送。
 */
export function handleDeepLink(rawUrl: string): void {
  const parsed = parseDesktopDeepLink(rawUrl)
  if (!parsed) return
  desktopRuntime.pendingDeepLink = parsed.raw
  writeBackendLog(`[deeplink] received host=${parsed.host} path=${parsed.path}\n`)
  const mainWindow = desktopRuntime.mainWindow
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show()
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
    broadcastToRenderer('xcagi:deep-link', parsed.raw)
  }
}

async function cookieHeaderForBackend(): Promise<string> {
  const url = `http://127.0.0.1:${DEFAULT_PORT}/`
  const cookies = await session.defaultSession.cookies.get({ url })
  if (!cookies.length) {
    return ''
  }
  return cookies.map(c => `${c.name}=${c.value}`).join('; ')
}

export async function exportSupportBundleInteractive(): Promise<void> {
  try {
    const cookie = await cookieHeaderForBackend()
    const headers: Record<string, string> = {}
    if (cookie) {
      headers.Cookie = cookie
    }
    const res = await fetch(`http://127.0.0.1:${DEFAULT_PORT}/api/desktop/support-bundle`, {
      headers
    })
    if (res.status === 401) {
      void dialog.showMessageBox({
        type: 'warning',
        title: APP_NAME,
        message: '请先登录后再导出诊断包'
      })
      return
    }
    if (!res.ok) {
      void dialog.showErrorBox(APP_NAME, `导出失败：HTTP ${res.status}`)
      return
    }
    const buf = Buffer.from(await res.arrayBuffer())
    const iso = new Date().toISOString().replace(/[:.]/g, '-')
    const defaultPath = path.join(app.getPath('downloads'), `xcagi-support-${iso}.zip`)
    const mainWindow = desktopRuntime.mainWindow
    const win = BrowserWindow.getFocusedWindow() ?? mainWindow
    const saveOpts = {
      title: '导出诊断包',
      defaultPath,
      filters: [{ name: 'ZIP', extensions: ['zip'] }]
    }
    const { canceled, filePath } = win
      ? await dialog.showSaveDialog(win, saveOpts)
      : await dialog.showSaveDialog(saveOpts)
    if (canceled || !filePath) {
      return
    }
    await fs.promises.writeFile(filePath, buf)
    const parent = win ?? mainWindow
    const saved = {
      type: 'info' as const,
      title: APP_NAME,
      message: '诊断包已保存',
      detail: filePath
    }
    if (parent) {
      void dialog.showMessageBox(parent, saved)
    } else {
      void dialog.showMessageBox(saved)
    }
  } catch (error) {
    void dialog.showErrorBox(
      APP_NAME,
      error instanceof Error ? error.message : String(error)
    )
  }
}

export function openKellaiDesktop(): Promise<{ ok: boolean; reason?: string }> {
  const notInstalledReason = '未检测到客来来桌面端，请先安装并打开一次客来来。'
  if (process.platform !== 'darwin') {
    return shell
      .openExternal('kellai://messages?source=xcmax')
      .then(() => ({ ok: true }))
      .catch(() => ({ ok: false, reason: notInstalledReason }))
  }

  return new Promise(resolve => {
    execFile('open', ['-b', KELLAI_BUNDLE_ID], error => {
      if (!error) {
        resolve({ ok: true })
        return
      }
      resolve({ ok: false, reason: notInstalledReason })
    })
  })
}

export function createMenu(): void {
  const appSubmenu: Electron.MenuItemConstructorOptions[] = [
    { label: '打开数据目录', click: () => void shell.openPath(app.getPath('userData')) },
    {
      label: '导出诊断包…',
      click: () => void exportSupportBundleInteractive()
    },
    { label: '检查更新', click: () => void runUpdateCheckWithDirectNet() },
    { type: 'separator' },
    { role: 'quit', label: '退出' }
  ]

  if (process.platform === 'darwin') {
    appSubmenu.unshift(
      { role: 'about', label: `关于 ${APP_NAME}` },
      { type: 'separator' },
      { role: 'services' },
      { type: 'separator' },
      { role: 'hide', label: `隐藏 ${APP_NAME}` },
      { role: 'hideOthers' },
      { role: 'unhide' },
      { type: 'separator' }
    )
  }

  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: APP_NAME,
      submenu: appSubmenu
    },
    { role: 'editMenu', label: '编辑' },
    { role: 'viewMenu', label: '视图' },
    { role: 'windowMenu', label: '窗口' }
  ]
  if (process.platform === 'darwin') {
    template.push({ role: 'help', label: '帮助' })
  }
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

function menuBarTrayIcon(): Electron.NativeImage | null {
  const iconPath = shellIconPath()
  if (!fs.existsSync(iconPath)) {
    return null
  }
  const image = nativeImage.createFromPath(iconPath)
  if (image.isEmpty()) {
    return null
  }
  // Windows 托盘须小图标；macOS 菜单栏禁止用大图（会撑满系统顶栏）
  const edge = process.platform === 'win32' ? 16 : 18
  const resized = image.resize({ width: edge, height: edge, quality: 'best' })
  if (process.platform === 'darwin') {
    resized.setTemplateImage(true)
  }
  return resized
}

export function createTray(): void {
  const image = menuBarTrayIcon()
  if (!image) {
    return
  }
  const tray = new Tray(image)
  desktopRuntime.tray = tray
  tray.setToolTip(APP_NAME)
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '显示 / 隐藏 XCAGI', click: () => toggleMainWindow() },
      { label: '打开数据目录', click: () => void shell.openPath(app.getPath('userData')) },
      { label: '导出诊断包…', click: () => void exportSupportBundleInteractive() },
      { label: '检查更新', click: () => void runUpdateCheckWithDirectNet() },
      { type: 'separator' },
      { label: '退出', click: () => app.quit() }
    ])
  )
}

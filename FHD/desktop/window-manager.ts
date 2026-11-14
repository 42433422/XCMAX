import { BrowserWindow, app, dialog, screen, session, shell } from 'electron'
import fs from 'node:fs'
import path from 'node:path'
import {
  APP_NAME,
  DEFAULT_PORT,
  desktopInitialUrl,
  markFrontendCacheCleared,
  shellIconPath,
  shouldClearFrontendCache,
} from './desktop-config'
import { desktopRuntime } from './runtime-state'
import {
  checkForceUpgrade,
  packagedBackendHealthTimeoutMs,
  showDbRecoveryDialogIfNeeded,
  waitForBackendApplicationReady,
  waitForBackendPing,
  waitForBackendStatus,
  writeBackendLog,
} from './backend-process'
import { DESKTOP_MIN_HEIGHT, DESKTOP_MIN_WIDTH, clampWindowBounds, readWindowState, writeWindowState } from './window-state'
import { checkPendingRollback } from './rollback'
import { configureUpdater } from './updater'
import { configureDesktopDownloads } from './desktop-downloads'
import { attachRendererSurfaceRecovery } from './renderer-surface'
import {
  handleDesktopWindowOpen,
  handleDesktopWillNavigate,
  isBenignDesktopLoadAbort,
  isTrustedDesktopOrigin,
} from './desktop-navigation'
import { reportRendererError } from './desktop-resilience'

/** 闪屏进度 0–100；供启动阶段与单测共用。 */
export function clampSplashProgress(percent: number): number {
  if (!Number.isFinite(percent)) return 0
  return Math.max(0, Math.min(100, Math.round(percent)))
}

function escapeSplashJsString(text: string): string {
  return text.replace(/\\/g, '\\\\').replace(/'/g, "\\'")
}

/** 更新启动闪屏进度条与文案，减少用户等待时的「卡住」恐慌感。 */
export function updateSplashProgress(
  percent: number,
  text?: string,
  opts?: { error?: boolean }
): void {
  const mainWindow = desktopRuntime.mainWindow
  if (!mainWindow || mainWindow.isDestroyed()) return
  const pct = clampSplashProgress(percent)
  const errorFlag = opts?.error ? ',{error:true}' : ''
  const js =
    text !== undefined
      ? `window.xcagiSetSplashProgress && window.xcagiSetSplashProgress(${pct},'${escapeSplashJsString(text)}'${errorFlag})`
      : `window.xcagiSetSplashProgress && window.xcagiSetSplashProgress(${pct}${errorFlag ? ',undefined' + errorFlag : ''})`
  void mainWindow.webContents.executeJavaScript(js).catch(() => undefined)
}

export function resolveDesktopSplashUrl(): string {
  const candidates = [
    path.join(__dirname, 'splash.html'),
    path.join(__dirname, '..', 'resources', 'splash.html')
  ]
  if (process.resourcesPath) {
    candidates.push(path.join(process.resourcesPath, 'splash.html'))
  }
  for (const filePath of candidates) {
    if (fs.existsSync(filePath)) {
      return `file://${filePath.replace(/\\/g, '/')}`
    }
  }
  const fallback = `<!doctype html><html><body style="margin:0;background:#f4f7fb;display:flex;align-items:center;justify-content:center;height:100vh;font-family:system-ui,sans-serif;color:#1a2b4a"><div style="text-align:center;min-width:280px"><div style="font-size:1.25rem;font-weight:600">XCAGI</div><div id="status" style="margin-top:12px;color:#5a6d8c">启动中…</div><div style="margin-top:16px;height:8px;background:#dce5f4;border-radius:99px;overflow:hidden"><div id="bar" style="height:100%;width:8%;background:#3b6fd9;border-radius:99px"></div></div><div id="pct" style="margin-top:8px;font-size:12px;color:#3b6fd9">8%</div></div><script>window.xcagiSetSplashStatus=function(t){var e=document.getElementById('status');if(e&&t)e.textContent=t};window.xcagiSetSplashProgress=function(p,t){var n=Math.max(0,Math.min(100,Math.round(Number(p)||0)));var b=document.getElementById('bar');var c=document.getElementById('pct');if(b)b.style.width=n+'%';if(c)c.textContent=n+'%';if(t)window.xcagiSetSplashStatus(t)};</script></body></html>`
  return `data:text/html;charset=utf-8,${encodeURIComponent(fallback)}`
}

/** 含主窗口在内的同时可见窗口上限。第二进程仍由 single-instance lock 拒绝。 */
export const MAX_DESKTOP_WINDOWS = 5

let auxiliaryPartitionSerial = 0

/** 每个附加窗口一个内存分区，localStorage / IndexedDB / Cache 不与主窗口或其他窗口互通。 */
export function nextAuxiliaryPartition(): string {
  auxiliaryPartitionSerial += 1
  return `xcagi-aux-${auxiliaryPartitionSerial}`
}

export function resetAuxiliaryPartitionSerialForTests(): void {
  auxiliaryPartitionSerial = 0
}

/**
 * 只复制本机业务源的 cookie，让附加窗口能沿用同一次登录。
 * 不复制 localStorage。弹窗、草稿和任务界面状态留在各自的存储分区里。
 */
export async function copyDesktopLoginCookies(target: Electron.Session): Promise<void> {
  const url = `http://127.0.0.1:${DEFAULT_PORT}/`
  let cookies: Electron.Cookie[] = []
  try {
    cookies = await session.defaultSession.cookies.get({ url })
  } catch {
    return
  }
  for (const cookie of cookies) {
    if (!cookie.name || cookie.value == null) continue
    const sameSite = cookie.sameSite === 'no_restriction'
      || cookie.sameSite === 'lax'
      || cookie.sameSite === 'strict'
      || cookie.sameSite === 'unspecified'
      ? cookie.sameSite
      : 'lax'
    try {
      await target.cookies.set({
        url,
        name: cookie.name,
        value: cookie.value,
        path: cookie.path || '/',
        secure: Boolean(cookie.secure),
        httpOnly: Boolean(cookie.httpOnly),
        expirationDate: cookie.expirationDate,
        sameSite,
      })
    } catch {
      /* 单条 cookie 失败不阻止开窗 */
    }
  }
}

function liveAuxiliaryWindows(): Electron.BrowserWindow[] {
  return [...desktopRuntime.auxiliaryWindows].filter(win => !win.isDestroyed())
}

export function desktopWindowCount(): number {
  const main = desktopRuntime.mainWindow && !desktopRuntime.mainWindow.isDestroyed() ? 1 : 0
  return main + liveAuxiliaryWindows().length
}

function attachAuxiliaryGuards(win: Electron.BrowserWindow): void {
  configureDesktopDownloads(win.webContents.session, () => app.getPath('downloads'), writeBackendLog)
  win.webContents.on('will-navigate', (event, url) => {
    handleDesktopWillNavigate(url, DEFAULT_PORT, () => event.preventDefault(), console.warn)
  })
  win.webContents.setWindowOpenHandler(({ url }) => openTrustedAuxiliaryFromHandler(url, win))
  win.on('closed', () => {
    desktopRuntime.auxiliaryWindows.delete(win)
  })
}

function openTrustedAuxiliaryFromHandler(
  url: string,
  owner: Electron.BrowserWindow,
): { action: 'deny' } {
  const decision = handleDesktopWindowOpen(
    url,
    DEFAULT_PORT,
    target => shell.openExternal(target),
    message => console.warn(message),
    target => owner.webContents.downloadURL(target),
  )
  if (decision === 'allow') openAuxiliaryWindow(url)
  return { action: 'deny' }
}

/**
 * 在当前进程再开一个业务窗口。后端仍是原来的 17500，登录 cookie 单独复制。
 * 存储分区不共享，关窗即销毁，不隐藏到托盘，也不再起一个后端。
 */
export function openAuxiliaryWindow(rawUrl: string): Electron.BrowserWindow | null {
  if (!isTrustedDesktopOrigin(rawUrl, DEFAULT_PORT)) {
    writeBackendLog('[window] refused untrusted auxiliary url\n')
    return null
  }
  if (desktopWindowCount() >= MAX_DESKTOP_WINDOWS) {
    writeBackendLog(`[window] refused auxiliary window; cap=${MAX_DESKTOP_WINDOWS}\n`)
    return null
  }
  const main = desktopRuntime.mainWindow
  const origin = main && !main.isDestroyed()
    ? main.getBounds()
    : { x: 40, y: 40, width: 1180, height: 760 }
  const index = liveAuxiliaryWindows().length + 1
  const icon = shellIconPath()
  const partition = nextAuxiliaryPartition()
  const isolated = session.fromPartition(partition)
  const win = new BrowserWindow({
    ...(fs.existsSync(icon) ? { icon } : {}),
    x: origin.x + 28 * index,
    y: origin.y + 28 * index,
    width: origin.width,
    height: origin.height,
    minWidth: 960,
    minHeight: 640,
    title: APP_NAME,
    autoHideMenuBar: process.platform !== 'darwin',
    show: true,
    backgroundColor: '#f4f7fb',
    webPreferences: {
      partition,
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  desktopRuntime.auxiliaryWindows.add(win)
  attachAuxiliaryGuards(win)
  win.on('closed', () => {
    void isolated.clearStorageData().catch(() => undefined)
    void isolated.clearCache().catch(() => undefined)
  })
  void (async () => {
    try {
      await copyDesktopLoginCookies(isolated)
      if (win.isDestroyed()) return
      await win.loadURL(rawUrl)
    } catch (error) {
      writeBackendLog(`[window] auxiliary load failed: ${error instanceof Error ? error.message : String(error)}\n`)
    }
  })()
  win.webContents.on('did-finish-load', () => tagDesktopWebContents(win))
  return win
}

export function broadcastToRenderer(channel: string, payload?: unknown): void {
  const mainWindow = desktopRuntime.mainWindow
  if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.webContents.isLoading()) {
    mainWindow.webContents.send(channel, payload)
  }
}

/**
 * 常驻模式下切换主窗口的显示/隐藏。
 * 窗口隐藏时后端保持常驻（不随窗口销毁），实现"关窗到托盘 + 秒开"。
 */
export function toggleMainWindow(): void {
  const mainWindow = desktopRuntime.mainWindow
  if (!mainWindow || mainWindow.isDestroyed()) {
    void createWindow()
    return
  }
  // 最小化窗口在 Windows 上 isVisible() 仍为 true，再 hide 会让托盘「显示」把窗口藏掉。
  if (mainWindow.isVisible() && !mainWindow.isMinimized()) {
    mainWindow.hide()
  } else {
    showMainWindow()
  }
}

/** 托盘唤起时，窗口若几乎不在当前工作区内，拉回该显示器，避免点了却看不见。 */
function bringOffscreenWindowIntoWorkArea(win: BrowserWindow): void {
  const bounds = win.getBounds()
  const work = screen.getDisplayMatching(bounds).workArea
  const overlapW = Math.min(bounds.x + bounds.width, work.x + work.width) - Math.max(bounds.x, work.x)
  const overlapH = Math.min(bounds.y + bounds.height, work.y + work.height) - Math.max(bounds.y, work.y)
  const visibleEnough =
    overlapW >= Math.min(240, bounds.width / 2) && overlapH >= Math.min(180, bounds.height / 2)
  if (visibleEnough) return
  win.setBounds(clampWindowBounds(bounds, work))
}

/**
 * 仅显示并聚焦主窗口（不隐藏），用于托盘单击、语音唤起、深链等“确保窗口可见”场景，
 * 区别于 toggleMainWindow 的显隐切换语义。
 */
export function showMainWindow(): void {
  const mainWindow = desktopRuntime.mainWindow
  if (!mainWindow || mainWindow.isDestroyed()) {
    void createWindow()
    return
  }
  if (mainWindow.isMinimized()) mainWindow.restore()
  bringOffscreenWindowIntoWorkArea(mainWindow)
  mainWindow.show()
  if (process.platform === 'darwin') {
    app.focus({ steal: true })
  }
  mainWindow.focus()
  if (process.platform === 'win32') {
    // 托盘单击拿不到前台许可，短暂置顶再取消，窗口才会真正露到最前。
    mainWindow.setAlwaysOnTop(true)
    mainWindow.moveTop()
    mainWindow.focus()
    mainWindow.setAlwaysOnTop(false)
  }
}

/** macOS 全屏/恢复后窗口可能只剩顶部一条，拉回工作区。 */
function ensureMacWindowInWorkArea(win: BrowserWindow): void {
  if (process.platform !== 'darwin') return
  const bounds = win.getBounds()
  const work = screen.getDisplayMatching(bounds).workArea
  const minW = DESKTOP_MIN_WIDTH
  const minH = DESKTOP_MIN_HEIGHT
  let { x, y, width, height } = bounds
  if (width < minW) width = Math.min(minW, work.width)
  if (height < minH) height = Math.min(minH, work.height)
  if (y < work.y || height < minH) {
    y = work.y + 8
    height = Math.min(Math.max(height, minH), work.height - 16)
  }
  if (x + width > work.x + work.width) {
    x = work.x + Math.max(0, work.width - width)
  }
  if (x < work.x) x = work.x
  if (width !== bounds.width || height !== bounds.height || x !== bounds.x || y !== bounds.y) {
    win.setBounds({ x, y, width, height })
  }
}

function tagDesktopWebContents(win: BrowserWindow): void {
  const platformClass =
    process.platform === 'darwin'
      ? 'xcagi-electron-mac'
      : process.platform === 'win32'
        ? 'xcagi-electron-win'
        : ''
  const sheet = platformClass === 'xcagi-electron-mac'
    ? 'mac'
    : platformClass === 'xcagi-electron-win'
      ? 'win'
      : ''
  // 闪屏是 file:// 内联页面，根相对路径 /platform/*.css 会被解析到磁盘根目录而 404。
  // 仅对本地应用页注入平台样式，且用应用基址拼出绝对 URL，与闪屏的内联样式一致地
  // 不依赖文档自身来源。
  const appOrigin = new URL(desktopInitialUrl()).origin
  const currentUrl = win.webContents.getURL()
  const injectSheet = sheet !== '' && currentUrl.startsWith(appOrigin)
  const sheetUrl = injectSheet ? new URL(`/platform/electron-${sheet}.css`, appOrigin).href : ''
  void win.webContents
    .executeJavaScript(
      `(() => {
        const root = document.documentElement;
        root.classList.add('xcagi-electron');
        root.classList.remove('xcagi-electron-mac', 'xcagi-electron-win');
        ${platformClass ? `root.classList.add('${platformClass}');` : ''}
        const sheet = ${injectSheet ? `'${sheet}'` : 'null'};
        if (!sheet) return;
        const other = sheet === 'win' ? 'mac' : 'win';
        const stale = document.getElementById('xcagi-platform-chrome-' + other);
        if (stale) stale.remove();
        const id = 'xcagi-platform-chrome-' + sheet;
        if (document.getElementById(id)) return;
        const link = document.createElement('link');
        link.id = id;
        link.rel = 'stylesheet';
        link.href = '${sheetUrl}';
        document.head.appendChild(link);
      })();`
    )
    .catch(() => { })
}

export async function createWindow(): Promise<void> {
  if (desktopRuntime.mainWindow && !desktopRuntime.mainWindow.isDestroyed()) return
  const icon = shellIconPath()
  const statePath = path.join(app.getPath('userData'), 'window-state.json')
  const savedBounds = readWindowState(statePath)
  const display = savedBounds
    ? screen.getDisplayMatching(savedBounds)
    : screen.getPrimaryDisplay()
  const initialBounds = clampWindowBounds(savedBounds, display.workArea)
  const winOpts: Electron.BrowserWindowConstructorOptions = {
    ...initialBounds,
    minWidth: DESKTOP_MIN_WIDTH,
    minHeight: DESKTOP_MIN_HEIGHT,
    title: APP_NAME,
    autoHideMenuBar: process.platform !== 'darwin',
    // Avoid exposing an empty native surface before the local splash has painted.
    show: false,
    backgroundColor: '#f4f7fb'
  }
  if (fs.existsSync(icon)) {
    winOpts.icon = icon
  }
  if (process.platform === 'darwin') {
    winOpts.frame = true
    winOpts.titleBarStyle = 'default'
  } else if (process.platform === 'win32') {
    // 与 macOS 平级观感（desktop-platform-parity SSOT）：隐藏原生标题栏带，
    // 用 titleBarOverlay 把系统 最小化/最大化/关闭 按钮悬浮进应用内顶栏，
    // 顶栏拖拽区由前端 CSS（-webkit-app-region）提供。
    winOpts.titleBarStyle = 'hidden'
    winOpts.titleBarOverlay = {
      color: '#ffffff',
      symbolColor: '#334155',
      height: 50
    }
  }
  const mainWindow = new BrowserWindow({ ...winOpts, webPreferences: {
    preload: path.join(__dirname, 'preload.js'),
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: true,
    backgroundThrottling: false,
  } })
  desktopRuntime.mainWindow = mainWindow
  attachRendererSurfaceRecovery(mainWindow, writeBackendLog)
  desktopRuntime.rendererFailedDuringStartup = false
  let startupWindowShown = false
  let lastRendererReloadAt = 0
  const showStartupWindow = () => {
    if (startupWindowShown || mainWindow.isDestroyed()) return
    startupWindowShown = true
    mainWindow.show()
    mainWindow.focus()
  }
  mainWindow.once('ready-to-show', showStartupWindow)
  let stateWriteTimer: NodeJS.Timeout | null = null
  const persistWindowState = () => {
    if (mainWindow.isDestroyed() || mainWindow.isMinimized() || mainWindow.isFullScreen()) return
    writeWindowState(statePath, mainWindow.getNormalBounds())
  }
  const scheduleWindowStateWrite = () => {
    if (stateWriteTimer) clearTimeout(stateWriteTimer)
    stateWriteTimer = setTimeout(() => {
      stateWriteTimer = null
      persistWindowState()
    }, 250)
  }
  mainWindow.on('move', scheduleWindowStateWrite)
  mainWindow.on('resize', scheduleWindowStateWrite)
  // 常驻：非退出时关窗仅隐藏到托盘，后端保持常驻实现"秒开"；仅托盘"退出"或
  // app.quit() 才真正关闭（isQuitting 已在 before-quit 置位）。
  mainWindow.on('close', (event) => {
    persistWindowState()
    if (!app.isQuitting) {
      event.preventDefault()
      mainWindow.hide()
    }
  })
  if (process.platform !== 'darwin') {
    mainWindow.setAutoHideMenuBar(true)
    mainWindow.setMenuBarVisibility(false)
  }

  mainWindow.on('closed', () => {
    if (stateWriteTimer) clearTimeout(stateWriteTimer)
    desktopRuntime.mainWindow = null
    desktopRuntime.mainApplicationReady = null
  })
  if (process.platform === 'darwin') {
    mainWindow.on('leave-full-screen', () => {
      if (desktopRuntime.mainWindow) ensureMacWindowInWorkArea(desktopRuntime.mainWindow)
    })
    mainWindow.on('restore', () => {
      if (desktopRuntime.mainWindow) ensureMacWindowInWorkArea(desktopRuntime.mainWindow)
    })
  }

  mainWindow.webContents.on('will-navigate', (event, url) => {
    handleDesktopWillNavigate(url, DEFAULT_PORT, () => event.preventDefault(), console.warn)
  })
  // 未注册 will-download 时 Chromium 只把文件留在下载目录的 <guid>.tmp，
  // 客户看不到「文件名: xxx.xlsx」对应的文件。显式落盘到下载目录并保留业务文件名。
  configureDesktopDownloads(mainWindow.webContents.session, () => app.getPath('downloads'), writeBackendLog)
  mainWindow.webContents.setWindowOpenHandler(({ url }) => openTrustedAuxiliaryFromHandler(url, mainWindow))
  const reportMainRenderer = (type: string, error: string, source?: string) => {
    reportRendererError({ port: DEFAULT_PORT, writeLog: writeBackendLog }, { type, error, source })
  }
  mainWindow.webContents.on('console-message', (...args: unknown[]) => {
    const details = (typeof args[1] === 'object' && args[1]) ? args[1] as { level?: string | number; message?: string; lineNumber?: number; sourceId?: string } : null
    const resolvedLevel = details ? details.level : args[1]
    const resolvedMessage = details ? String(details.message || '') : String(args[2] || '')
    const resolvedLine = details ? details.lineNumber : args[3]
    const resolvedSource = details ? details.sourceId : args[4]
    const isError = resolvedLevel === 'error' || resolvedLevel === 3
    if (!isError || !resolvedMessage.trim()) return
    reportMainRenderer(
      'renderer:console',
      resolvedMessage.trim().slice(0, 4000),
      [resolvedSource, resolvedLine].filter((part) => part !== undefined && part !== '').join(':'),
    )
  })
  mainWindow.webContents.on('unresponsive', () => {
    writeBackendLog('[crash] renderer unresponsive\n')
    reportMainRenderer('renderer:unresponsive', 'renderer process is unresponsive')
  })
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    // 各平台对「正常退出」的判定不同：macOS 常见 clean-exit，Windows 也会用
    // clean-exit 配非零 exitCode，或直接报 killed。只把无异常的退出当作正常。
    const cleanExit = details.reason === 'clean-exit' && (details.exitCode ?? 0) === 0
    if (cleanExit) return
    let crashDumpsPath = 'unavailable'
    let source = desktopInitialUrl()
    try {
      crashDumpsPath = app.getPath('crashDumps')
    } catch {
      /* 崩溃路径不可用时仍要记录进程退出原因 */
    }
    try {
      source = mainWindow.webContents.getURL() || source
    } catch {
      /* webContents 可能已随渲染进程销毁 */
    }
    const summary = `reason=${details.reason} exitCode=${details.exitCode} crashDumps=${crashDumpsPath}`
    writeBackendLog(`[crash] renderer gone ${summary}\n`)
    reportMainRenderer('renderer:gone', summary, source)
    if (checkPendingRollback()) {
      desktopRuntime.rendererFailedDuringStartup = true
      return
    }
    if (!app.isQuitting && !mainWindow.isDestroyed()) {
      const now = Date.now()
      if (now - lastRendererReloadAt < 3000) {
        writeBackendLog(`[crash] skip reload; renderer crashed again within 3s (${summary})\n`)
        return
      }
      lastRendererReloadAt = now
      // Reload the same document. Quitting or sending the user to login drops a still-valid session.
      writeBackendLog(`[crash] reloading renderer in place after ${summary}\n`)
      mainWindow.reload()
    }
  })

  desktopRuntime.splashUrl = resolveDesktopSplashUrl()
  void mainWindow.loadURL(desktopRuntime.splashUrl).catch(error => {
    // The backend may become ready while the splash is still loading. Its
    // replacement navigation must still wait for a painted renderer to show.
    if (error instanceof Error && /ERR_ABORTED/i.test(error.message)) return
    console.error('[xcagi-desktop] load startup splash failed', error)
    showStartupWindow()
  })
  updateSplashProgress(8, '正在启动本地服务…')

  // 版本/构建哈希变化后必须先完成缓存清理，再加载入口页；否则旧 index.html 会继续
  // 引用已被删除的 JS/CSS chunk，表现为动态 import、图片和模块路由成批加载失败。
  let frontendCacheReady: Promise<void> = Promise.resolve()
  if (shouldClearFrontendCache()) {
    frontendCacheReady = mainWindow.webContents.session
      .clearCache()
      .then(() => {
        markFrontendCacheCleared()
        writeBackendLog('[cache] frontend cache cleared for new build\n')
      })
      .catch(error => {
        writeBackendLog(
          `[cache] frontend cache clear failed: ${error instanceof Error ? error.message : String(error)}\n`,
        )
      })
  }

  const loadMainApplication = async (): Promise<void> => {
    if (!desktopRuntime.mainWindow) {
      throw new Error('主窗口在应用加载前已关闭')
    }
    try {
      updateSplashProgress(92, '正在打开主界面…')
      await frontendCacheReady
      await desktopRuntime.mainWindow.loadURL(desktopInitialUrl(), {
        extraHeaders: 'Cache-Control: no-cache\r\n'
      })
      tagDesktopWebContents(desktopRuntime.mainWindow)
      if (process.platform === 'darwin') {
        ensureMacWindowInWorkArea(desktopRuntime.mainWindow)
      }
      if (startupWindowShown) desktopRuntime.mainWindow.focus()
    } catch (error) {
      const currentUrl = desktopRuntime.mainWindow?.webContents.getURL()
      if (isBenignDesktopLoadAbort(error, currentUrl, DEFAULT_PORT)) {
        console.warn('[xcagi-desktop] ignored transient local-page navigation abort', error)
        return
      }
      console.error('[xcagi-desktop] load main application failed', error)
      throw error
    }
  }

  const splashStarted = Date.now()
  const splashBudgetMs = packagedBackendHealthTimeoutMs()
  let splashPhase: 'boot' | 'routes' | 'done' = 'boot'
  let phaseStarted = splashStarted
  const splashTicker = setInterval(() => {
    if (!desktopRuntime.mainWindow || desktopRuntime.mainWindow.isDestroyed() || splashPhase === 'done') {
      clearInterval(splashTicker)
      return
    }
    const elapsed = Date.now() - phaseStarted
    if (splashPhase === 'boot') {
      // 后端拉起阶段：8% → 55%，按预算时间缓爬，始终有可见推进
      const creep = 8 + Math.min(47, (elapsed / splashBudgetMs) * 47)
      updateSplashProgress(creep, '正在启动本地服务…')
      return
    }
    // 路由/模块就绪阶段：58% → 85%
    const creep = 58 + Math.min(27, (elapsed / Math.max(15_000, splashBudgetMs * 0.35)) * 27)
    updateSplashProgress(creep, '正在加载业务模块…')
  }, 400)

  const pingReady = waitForBackendPing(DEFAULT_PORT)
    .then(() => {
      splashPhase = 'routes'
      phaseStarted = Date.now()
      updateSplashProgress(58, '本地服务已就绪，正在打开工作台…')
    })

  const backendApplicationReady = pingReady.then(() =>
    waitForBackendApplicationReady(DEFAULT_PORT, undefined, { skipPing: true }),
  )
  // 不在业务路由注册完成前发起登录及工作台请求。
  const mainUiReady = backendApplicationReady.then(() => {
      splashPhase = 'done'
      updateSplashProgress(88, '正在加载应用…')
      return loadMainApplication()
    })
  const ready = Promise.all([mainUiReady, backendApplicationReady]).then(() => undefined)
  desktopRuntime.mainApplicationReady = ready
  void mainUiReady.then(
    () => clearInterval(splashTicker),
    () => clearInterval(splashTicker),
  )
  void ready
    .catch(error => {
      console.error('[xcagi-desktop] backend readiness wait failed', error)
      splashPhase = 'done'
      updateSplashProgress(100, '启动失败，请查看日志', { error: true })
      if (!checkPendingRollback()) {
        void dialog.showErrorBox(APP_NAME, error instanceof Error ? error.message : String(error))
      }
    })

  mainWindow.webContents.on('did-finish-load', () => {
    if (desktopRuntime.mainWindow) tagDesktopWebContents(desktopRuntime.mainWindow)
  })

  void waitForBackendStatus(DEFAULT_PORT).then(status => {
    console.info(
      '[xcagi-desktop] startup',
      JSON.stringify({
        ...desktopRuntime.startupMarks,
        desktopStatusOk: status !== null
      })
    )
    void showDbRecoveryDialogIfNeeded(status)
  })

  // E2E（XCAGI_DESKTOP_E2E=1）跳过 updater 挂载：避免 60s 后的真实 OTA 检查出网。
  if (process.env.XCAGI_DESKTOP_E2E !== '1') {
    configureUpdater(mainWindow, { onForceUpgradeRequired: checkForceUpgrade })
  }
}

export async function waitForMainApplicationReady(): Promise<void> {
  if (!desktopRuntime.mainApplicationReady) {
    throw new Error('主界面就绪任务未初始化')
  }
  await desktopRuntime.mainApplicationReady
}

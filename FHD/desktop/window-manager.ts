import { BrowserWindow, app, dialog, screen, shell } from 'electron'
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
import { clampWindowBounds, readWindowState, writeWindowState } from './window-state'
import { checkPendingRollback } from './rollback'
import { configureUpdater } from './updater'
import {
  handleDesktopWindowOpen,
  isBenignDesktopLoadAbort,
  isTrustedDesktopOrigin,
} from './desktop-navigation'

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
  if (mainWindow.isVisible()) {
    mainWindow.hide()
  } else {
    mainWindow.show()
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  }
}

/** macOS 全屏/恢复后窗口可能只剩顶部一条，拉回工作区。 */
function ensureMacWindowInWorkArea(win: BrowserWindow): void {
  if (process.platform !== 'darwin') return
  const bounds = win.getBounds()
  const work = screen.getDisplayMatching(bounds).workArea
  const minW = 1180
  const minH = 760
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
  const classes = ['xcagi-electron']
  if (process.platform === 'darwin') classes.push('xcagi-electron-mac')
  if (process.platform === 'win32') classes.push('xcagi-electron-win')
  void win.webContents
    .executeJavaScript(
      classes.map(c => `document.documentElement.classList.add('${c}');`).join('')
    )
    .catch(() => { })
}

export async function createWindow(): Promise<void> {
  const icon = shellIconPath()
  const statePath = path.join(app.getPath('userData'), 'window-state.json')
  const savedBounds = readWindowState(statePath)
  const display = savedBounds
    ? screen.getDisplayMatching(savedBounds)
    : screen.getPrimaryDisplay()
  const initialBounds = clampWindowBounds(savedBounds, display.workArea)
  const winOpts: Electron.BrowserWindowConstructorOptions = {
    ...initialBounds,
    minWidth: 1180,
    minHeight: 760,
    title: APP_NAME,
    autoHideMenuBar: process.platform !== 'darwin',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  }
  if (fs.existsSync(icon)) {
    winOpts.icon = icon
  }
  if (process.platform === 'darwin') {
    winOpts.frame = true
    winOpts.titleBarStyle = 'default'
  }
  winOpts.show = true
  winOpts.backgroundColor = '#f4f7fb'
  const mainWindow = new BrowserWindow(winOpts)
  desktopRuntime.mainWindow = mainWindow
  desktopRuntime.rendererFailedDuringStartup = false
  const createdWindow = mainWindow
  let stateWriteTimer: NodeJS.Timeout | null = null
  const persistWindowState = () => {
    if (createdWindow.isDestroyed() || createdWindow.isMinimized() || createdWindow.isFullScreen()) return
    writeWindowState(statePath, createdWindow.getNormalBounds())
  }
  const scheduleWindowStateWrite = () => {
    if (stateWriteTimer) clearTimeout(stateWriteTimer)
    stateWriteTimer = setTimeout(() => {
      stateWriteTimer = null
      persistWindowState()
    }, 250)
  }
  createdWindow.on('move', scheduleWindowStateWrite)
  createdWindow.on('resize', scheduleWindowStateWrite)
  // 常驻：非退出时关窗仅隐藏到托盘，后端保持常驻实现"秒开"；仅托盘"退出"或
  // app.quit() 才真正关闭（isQuitting 已在 before-quit 置位）。
  createdWindow.on('close', (event) => {
    persistWindowState()
    if (!app.isQuitting) {
      event.preventDefault()
      createdWindow.hide()
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
    if (!isTrustedDesktopOrigin(url, DEFAULT_PORT) && !url.startsWith('file://') && !url.startsWith('data:')) {
      event.preventDefault()
      console.warn(`[xcagi-desktop] blocked will-navigate to ${url}`)
    }
  })
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    return { action: handleDesktopWindowOpen(url, DEFAULT_PORT, target => shell.openExternal(target), message => console.warn(message)) }
  })
  mainWindow.webContents.on('unresponsive', () => {
    writeBackendLog('[crash] renderer unresponsive\n')
  })
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    writeBackendLog(`[crash] renderer gone reason=${details.reason} exitCode=${details.exitCode}\n`)
    if (checkPendingRollback()) {
      desktopRuntime.rendererFailedDuringStartup = true
      return
    }
    if (!app.isQuitting && details.reason !== 'clean-exit') {
      void dialog.showMessageBox(createdWindow, {
        type: 'error',
        title: APP_NAME,
        message: '界面进程意外退出',
        detail: '崩溃信息已保存在数据目录。可以重新加载界面继续工作，后端与本地数据不会被清除。',
        buttons: ['重新加载', '退出'],
        defaultId: 0,
        cancelId: 1,
      }).then(({ response }) => {
        if (response === 0 && !createdWindow.isDestroyed()) createdWindow.reload()
        else app.quit()
      })
    }
  })

  void mainWindow.loadURL(resolveDesktopSplashUrl())
  mainWindow.show()
  mainWindow.focus()
  updateSplashProgress(8, '正在启动本地服务…')

  if (shouldClearFrontendCache()) {
    void mainWindow.webContents.session
      .clearCache()
      .then(() => markFrontendCacheCleared())
      .catch(() => undefined)
  }

  const loadMainApplication = async (): Promise<void> => {
    if (!desktopRuntime.mainWindow) {
      throw new Error('主窗口在应用加载前已关闭')
    }
    try {
      updateSplashProgress(92, '正在打开主界面…')
      await desktopRuntime.mainWindow.loadURL(desktopInitialUrl(), {
        extraHeaders: 'Cache-Control: no-cache\r\n'
      })
      tagDesktopWebContents(desktopRuntime.mainWindow)
      if (process.platform === 'darwin') {
        ensureMacWindowInWorkArea(desktopRuntime.mainWindow)
      }
      desktopRuntime.mainWindow.focus()
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

  // 登录后的工作台不必等待全部 Mod 和业务路由完成。先在本地服务
  // 可响应时打开界面，模块继续在后台完成；更新观察期仍会等待两者。
  const mainUiReady = pingReady.then(() => {
      splashPhase = 'done'
      updateSplashProgress(88, '正在加载应用…')
      return loadMainApplication()
    })
  const backendApplicationReady = pingReady.then(() =>
    waitForBackendApplicationReady(DEFAULT_PORT, undefined, { skipPing: true }),
  )
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

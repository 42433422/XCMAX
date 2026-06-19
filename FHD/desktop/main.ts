import {
  BrowserWindow,
  Menu,
  Notification,
  Tray,
  app,
  dialog,
  ipcMain,
  nativeImage,
  screen,
  shell
} from 'electron'
import { ChildProcessWithoutNullStreams, execFile, spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import { networkInterfaces } from 'node:os'
import path from 'node:path'
import { checkForUpdates, configureUpdater, installUpdate } from './updater'

const APP_NAME = 'XCAGI'

// 与 paths.py / 安装器太阳鸟种子目录一致（勿用 package.json 默认 xcagi-desktop）
app.setPath('userData', path.join(app.getPath('appData'), 'XCAGI'))

/** macOS 12+「隔空播放接收器」占用 :5000，TCP 可达但返回 AirTunes 空 403 → Electron 白屏。 */
function resolveDefaultDesktopPort(): number {
  const env = process.env.XCAGI_DESKTOP_PORT
  if (env) {
    return Number(env)
  }
  return process.platform === 'darwin' ? 17500 : 5000
}

const DEFAULT_PORT = resolveDefaultDesktopPort()

type ProductSku = 'personal' | 'enterprise'

const SKU_RUNTIME_EDITION: Record<ProductSku, string> = {
  personal: 'minimal',
  enterprise: 'full'
}

const SKU_UPDATE_URL: Record<ProductSku, string> = {
  personal: 'https://update.xcagi.com/releases/stable/personal/',
  enterprise: 'https://update.xcagi.com/releases/stable/enterprise/'
}

/** 企业版与网页 :5001 一致：完整侧栏，不强制 ?shell=1 */
function desktopInitialUrl(): string {
  const base = `http://127.0.0.1:${DEFAULT_PORT}/`
  if (readPackagedProductSku() === 'enterprise') {
    return base
  }
  return `${base}?shell=1`
}

function readPackagedProductSku(): ProductSku | null {
  if (!app.isPackaged) {
    const sku = String(process.env.XCAGI_PRODUCT_SKU || '').trim().toLowerCase()
    if (sku === 'personal' || sku === 'enterprise') {
      return sku
    }
    return null
  }
  const candidates = [
    path.join(process.resourcesPath, 'product-sku.json'),
    path.join(process.resourcesPath, 'backend', 'product-sku.json')
  ]
  for (const filePath of candidates) {
    try {
      if (!fs.existsSync(filePath)) continue
      const raw = JSON.parse(fs.readFileSync(filePath, 'utf8')) as { sku?: string }
      const sku = String(raw.sku || '').trim().toLowerCase()
      if (sku === 'personal' || sku === 'enterprise') {
        return sku
      }
    } catch {
      /* ignore */
    }
  }
  return null
}

function backendEditionEnv(): Record<string, string> {
  const sku = readPackagedProductSku()
  if (!sku) {
    return {
      XCAGI_GENERIC_EDITION: '1',
      XCAGI_PLATFORM_SHELL: '1',
      XCAGI_DEFAULT_EDITION: 'generic'
    }
  }
  const edition = SKU_RUNTIME_EDITION[sku]
  const env: Record<string, string> = {
    XCAGI_PRODUCT_SKU: sku,
    XCAGI_PLATFORM_SHELL: sku === 'enterprise' ? '0' : '1',
    XCAGI_DEFAULT_EDITION: edition,
    XCAGI_EDITION: edition
  }
  if (edition === 'minimal') {
    env.XCAGI_MINIMAL_EDITION = '1'
  } else if (edition === 'generic') {
    env.XCAGI_GENERIC_EDITION = '1'
  }
  return env
}

let mainWindow: BrowserWindow | null = null
let backendProcess: ChildProcessWithoutNullStreams | null = null
let backendLogStream: fs.WriteStream | null = null
let tray: Tray | null = null
let restartCount = 0

function repoRoot(): string {
  return app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '..', '..')
}

/** 托盘与窗口图标：与 dist 同级打包的 resources（由 beforePack 生成）。 */
function shellIconPath(): string {
  const name = process.platform === 'win32' ? 'icon.ico' : 'icon.png'
  return path.join(__dirname, '..', 'resources', name)
}

function packagedBackendCandidates(): string[] {
  const backendDir = path.join(process.resourcesPath, 'backend')
  const exe = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
  return [
    path.join(backendDir, exe),
    path.join(backendDir, 'xcagi-backend', exe),
    path.join(backendDir, '_internal', exe)
  ]
}

function findPackagedBackendExecutable(): string {
  const candidates = packagedBackendCandidates()
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate
    }
  }
  return candidates[0]
}

function backendExecutable(): { command: string; args: string[]; cwd: string } {
  const dataDir = app.getPath('userData')
  if (!app.isPackaged) {
    const root = repoRoot()
    return {
      command: process.env.PYTHON || 'python',
      args: [
        path.join(root, 'XCAGI', 'run.py'),
        '--desktop',
        '--headless',
        '--host',
        '127.0.0.1',
        '--port',
        String(DEFAULT_PORT),
        '--data-dir',
        dataDir
      ],
      cwd: root
    }
  }

  const command = findPackagedBackendExecutable()

  return {
    command,
    args: [
      '--desktop',
      '--headless',
      '--host',
      '127.0.0.1',
      '--port',
      String(DEFAULT_PORT),
      '--data-dir',
      dataDir
    ],
    cwd: path.dirname(command)
  }
}

function ensureBackendLogStream(): fs.WriteStream | null {
  if (backendLogStream) {
    return backendLogStream
  }
  try {
    const logDir = path.join(app.getPath('userData'), 'logs')
    fs.mkdirSync(logDir, { recursive: true })
    backendLogStream = fs.createWriteStream(path.join(logDir, 'electron-backend.log'), {
      flags: 'a'
    })
    backendLogStream.write(`\n[${new Date().toISOString()}] XCAGI desktop backend bootstrap\n`)
    backendLogStream.write(
      JSON.stringify(
        {
          platform: process.platform,
          arch: process.arch,
          packaged: app.isPackaged,
          resourcesPath: app.isPackaged ? process.resourcesPath : null,
          userData: app.getPath('userData'),
          sku: readPackagedProductSku() || 'generic'
        },
        null,
        2
      ) + '\n'
    )
    return backendLogStream
  } catch {
    return null
  }
}

function writeBackendLog(line: string): void {
  try {
    ensureBackendLogStream()?.write(line)
  } catch {
    /* ignore logging failures */
  }
}

function packagedBackendHealthTimeoutMs(): number {
  if (!app.isPackaged) {
    return 60_000
  }
  // 首次启动：Alembic、Mod 种子、太阳鸟花名册等可能超过 60s
  return process.platform === 'win32' ? 180_000 : 120_000
}

/** 须确认 uvicorn /api/health，避免 macOS AirPlay 占 5000 时 TCP 误判就绪。 */
async function waitForBackendHealth(port: number, timeoutMs = packagedBackendHealthTimeoutMs()): Promise<void> {
  const started = Date.now()
  while (Date.now() - started <= timeoutMs) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`, {
        signal: AbortSignal.timeout(3_000)
      })
      const server = (response.headers.get('server') || '').toLowerCase()
      if (response.ok && server.includes('uvicorn')) {
        startupMarks.tcp5000Ms = Date.now() - (startupMarks.backendSpawnMs ?? started)
        return
      }
      if (server.includes('airtunes')) {
        console.warn(`[xcagi-desktop] 端口 ${port} 被 macOS 隔空播放占用，等待 XCAGI 后端…`)
      }
    } catch {
      /* backend still booting */
    }
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  const airplayHint =
    process.platform === 'darwin' && port === 5000
      ? ' macOS「隔空播放接收器」占用 5000，请在系统设置中关闭，或设置 XCAGI_DESKTOP_PORT=17500。'
      : ''
  const firstBootHint = app.isPackaged
    ? ' 若仍失败，请查看数据目录 logs/ 下后端日志，或从菜单导出诊断包。'
    : ''
  throw new Error(
    `后端 /api/health 在 ${timeoutMs}ms 内未就绪（端口 ${port}）。${airplayHint}${firstBootHint}`
  )
}

type DesktopStartupMarks = {
  backendSpawnMs?: number
  tcp5000Ms?: number
  desktopStatusMs?: number
}

const startupMarks: DesktopStartupMarks = {}

function readPackagedAppVersion(): string {
  if (!app.isPackaged) return 'dev'
  const candidates = [
    path.join(process.resourcesPath, 'backend', 'version.txt'),
    path.join(process.resourcesPath, 'product-sku.json')
  ]
  for (const filePath of candidates) {
    try {
      if (!fs.existsSync(filePath)) continue
      const raw = fs.readFileSync(filePath, 'utf8').trim()
      if (filePath.endsWith('version.txt')) return raw || 'unknown'
      const json = JSON.parse(raw) as { sku?: string; schema_version?: number }
      return `${json.sku || 'enterprise'}-${json.schema_version ?? 1}`
    } catch {
      /* ignore */
    }
  }
  return app.getVersion()
}

/** 前端 hash 变更时须清 Electron 缓存，避免旧 index-*.js 引用已不存在的 chunk。 */
function readFrontendCacheKey(): string {
  const base = readPackagedAppVersion()
  const indexCandidates = [
    path.join(process.resourcesPath, 'backend', '_internal', 'templates', 'vue-dist', 'index.html'),
    path.join(process.resourcesPath, 'frontend', 'index.html')
  ]
  for (const indexPath of indexCandidates) {
    try {
      if (!fs.existsSync(indexPath)) continue
      const html = fs.readFileSync(indexPath, 'utf8')
      const match = html.match(/\/assets\/js\/index-([A-Za-z0-9_-]+)\.js/)
      if (match?.[1]) {
        return `${base}@${match[1]}`
      }
    } catch {
      /* ignore */
    }
  }
  return base
}

function shouldClearFrontendCache(): boolean {
  const marker = path.join(app.getPath('userData'), 'frontend-cache-version.txt')
  const current = readFrontendCacheKey()
  try {
    const prev = fs.readFileSync(marker, 'utf8').trim()
    return prev !== current
  } catch {
    return true
  }
}

function markFrontendCacheCleared(): void {
  const marker = path.join(app.getPath('userData'), 'frontend-cache-version.txt')
  fs.writeFileSync(marker, readFrontendCacheKey(), 'utf8')
}

/** 分阶段就绪：TCP 后即可出窗；desktop/status 软等待，不阻塞 60s 全量 Mod。 */
async function waitForBackendStatus(port: number, timeoutMs = 15_000): Promise<boolean> {
  const started = Date.now()
  while (Date.now() - started <= timeoutMs) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/desktop/status`)
      if (response.ok) {
        startupMarks.desktopStatusMs = Date.now() - (startupMarks.backendSpawnMs ?? started)
        return true
      }
    } catch {
      /* backend still importing routers */
    }
    await new Promise(resolve => setTimeout(resolve, 400))
  }
  console.warn(`[xcagi-desktop] /api/desktop/status 未在 ${timeoutMs}ms 内就绪，仍加载前端`)
  return false
}

function startBackend(): void {
  if (backendProcess) {
    return
  }

  const executable = backendExecutable()
  if (app.isPackaged && !fs.existsSync(executable.command)) {
    const candidates = packagedBackendCandidates().map(candidate => `- ${candidate}`).join('\n')
    const detail =
      `找不到后端程序：${executable.command}\n\n` +
      `已检查：\n${candidates}\n\n` +
      `请确认安装包包含 resources/backend/${process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'}。`
    writeBackendLog(`[error] ${detail}\n`)
    void dialog.showErrorBox(APP_NAME, detail)
    return
  }

  startupMarks.backendSpawnMs = Date.now()
  writeBackendLog(`[spawn] ${executable.command} ${executable.args.join(' ')}\n`)
  writeBackendLog(`[cwd] ${executable.cwd}\n`)
  backendProcess = spawn(executable.command, executable.args, {
    cwd: executable.cwd,
    env: {
      ...process.env,
      XCAGI_DESKTOP_MODE: '1',
      XCAGI_DATA_DIR: app.getPath('userData'),
      XCAGI_UVICORN_RELOAD: '0',
      ...backendEditionEnv(),
      PYTHONUTF8: '1'
    },
    windowsHide: true
  })

  backendProcess.stdout.on('data', data => {
    process.stdout.write(`[xcagi-backend] ${data}`)
    writeBackendLog(`[stdout] ${data}`)
  })
  backendProcess.stderr.on('data', data => {
    process.stderr.write(`[xcagi-backend] ${data}`)
    writeBackendLog(`[stderr] ${data}`)
  })
  backendProcess.on('error', error => {
    backendProcess = null
    writeBackendLog(`[error] backend spawn failed: ${error.message}\n`)
    if (!app.isQuitting) {
      void dialog.showErrorBox(APP_NAME, `后端服务启动失败：${error.message}`)
    }
  })
  backendProcess.on('exit', code => {
    writeBackendLog(`[exit] backend process exited code=${code}\n`)
    backendProcess = null
    if (app.isQuitting) {
      return
    }
    restartCount += 1
    if (restartCount <= 3) {
      setTimeout(startBackend, 1500)
      return
    }
    void dialog.showErrorBox(APP_NAME, `后端服务已退出（code=${code}），请重启 XCAGI。`)
  })
}

function runBackendMigration(): Promise<void> {
  const executable = backendExecutable()
  return new Promise((resolve, reject) => {
    const child = spawn(executable.command, [...executable.args, '--migrate-only', '--backup'], {
      cwd: executable.cwd,
      env: {
        ...process.env,
        XCAGI_DESKTOP_MODE: '1',
        XCAGI_DATA_DIR: app.getPath('userData'),
        XCAGI_UVICORN_RELOAD: '0',
        ...backendEditionEnv(),
        PYTHONUTF8: '1'
      },
      windowsHide: true
    })
    let stderr = ''
    child.stderr.on('data', data => {
      stderr += String(data)
      process.stderr.write(`[xcagi-migrate] ${data}`)
    })
    child.stdout.on('data', data => process.stdout.write(`[xcagi-migrate] ${data}`))
    child.on('error', reject)
    child.on('exit', code => {
      if (code === 0) {
        resolve()
      } else {
        reject(new Error(`数据库迁移失败（code=${code}）: ${stderr}`))
      }
    })
  })
}

async function exportSupportBundleInteractive(): Promise<void> {
  try {
    const res = await fetch(`http://127.0.0.1:${DEFAULT_PORT}/api/desktop/support-bundle`)
    if (!res.ok) {
      void dialog.showErrorBox(APP_NAME, `导出失败：HTTP ${res.status}`)
      return
    }
    const buf = Buffer.from(await res.arrayBuffer())
    const iso = new Date().toISOString().replace(/[:.]/g, '-')
    const defaultPath = path.join(app.getPath('downloads'), `xcagi-support-${iso}.zip`)
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
    .catch(() => {})
}

function stopBackend(): void {
  const child = backendProcess
  backendProcess = null
  if (!child || child.killed) {
    return
  }
  writeBackendLog(`[${new Date().toISOString()}] backend stop requested\n`)
  if (process.platform === 'win32' && child.pid) {
    execFile('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true }, error => {
      if (error && !child.killed) {
        child.kill()
      }
    })
  } else {
    child.kill('SIGTERM')
  }
  backendLogStream?.end(`[${new Date().toISOString()}] backend log closed\n`)
  backendLogStream = null
}

async function createWindow(): Promise<void> {
  const icon = shellIconPath()
  const winOpts: Electron.BrowserWindowConstructorOptions = {
    width: 1440,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    title: APP_NAME,
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
  winOpts.show = false
  winOpts.backgroundColor = '#f4f7fb'
  mainWindow = new BrowserWindow(winOpts)

  mainWindow.on('closed', () => {
    mainWindow = null
  })
  if (process.platform === 'darwin') {
    mainWindow.on('leave-full-screen', () => {
      if (mainWindow) ensureMacWindowInWorkArea(mainWindow)
    })
    mainWindow.on('restore', () => {
      if (mainWindow) ensureMacWindowInWorkArea(mainWindow)
    })
  }

  await waitForBackendHealth(DEFAULT_PORT)

  if (shouldClearFrontendCache()) {
    try {
      await mainWindow.webContents.session.clearCache()
      markFrontendCacheCleared()
    } catch {
      /* ignore */
    }
  }

  mainWindow.webContents.on('did-finish-load', () => {
    if (mainWindow) tagDesktopWebContents(mainWindow)
  })

  await mainWindow.loadURL(desktopInitialUrl(), {
    extraHeaders: 'Cache-Control: no-cache\r\n'
  })
  tagDesktopWebContents(mainWindow)
  if (process.platform === 'darwin') {
    ensureMacWindowInWorkArea(mainWindow)
  }
  mainWindow.show()
  mainWindow.focus()

  void waitForBackendStatus(DEFAULT_PORT).then(ok => {
    console.info(
      '[xcagi-desktop] startup',
      JSON.stringify({
        ...startupMarks,
        desktopStatusOk: ok
      })
    )
  })

  configureUpdater(mainWindow, runBackendMigration)
}

function createMenu(): void {
  const appSubmenu: Electron.MenuItemConstructorOptions[] = [
    { label: '打开数据目录', click: () => void shell.openPath(app.getPath('userData')) },
    {
      label: '导出诊断包…',
      click: () => void exportSupportBundleInteractive()
    },
    { label: '检查更新', click: () => void checkForUpdates() },
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

function createTray(): void {
  // macOS：与 Cursor 等原生应用一致，不占系统菜单栏右侧；仅 Dock + 左上角「XCAGI」文字菜单
  if (process.platform === 'darwin') {
    return
  }
  const image = menuBarTrayIcon()
  if (!image) {
    return
  }
  tray = new Tray(image)
  tray.setToolTip(APP_NAME)
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '显示 XCAGI', click: () => mainWindow?.show() },
      { label: '打开数据目录', click: () => void shell.openPath(app.getPath('userData')) },
      { type: 'separator' },
      { label: '退出', click: () => app.quit() }
    ])
  )
}

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  app.on('before-quit', () => {
    app.isQuitting = true
    stopBackend()
  })

  app.whenReady().then(async () => {
    const sku = readPackagedProductSku()
    if (sku && !process.env.XCAGI_UPDATE_URL) {
      process.env.XCAGI_UPDATE_URL = SKU_UPDATE_URL[sku]
    }
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

    ipcMain.handle('xcagi:pairing-qr', async () => {
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

    ipcMain.handle('xcagi:get-data-dir', () => app.getPath('userData'))
    ipcMain.handle('xcagi:export-support-bundle', () => exportSupportBundleInteractive())
    ipcMain.handle('xcagi:check-for-updates', () => checkForUpdates())
    ipcMain.handle('xcagi:install-update', () => installUpdate(runBackendMigration))
    ipcMain.handle('xcagi:set-badge', (_event, count: number) => {
      const n = Math.max(0, Math.floor(Number(count) || 0))
      if (process.platform === 'darwin' || process.platform === 'linux') {
        app.setBadgeCount(n)
        return
      }
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
        new Notification({ title, body }).show()
        return { ok: true }
      }
    )

    createMenu()
    createTray()
    startBackend()
    try {
      await createWindow()
    } catch (error) {
      void dialog.showErrorBox(APP_NAME, error instanceof Error ? error.message : String(error))
      app.quit()
    }
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void createWindow()
    }
  })
}

declare global {
  namespace Electron {
    interface App {
      isQuitting?: boolean
    }
  }
}

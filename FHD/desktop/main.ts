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
  session,
  shell
} from 'electron'
import { ChildProcessWithoutNullStreams, execFile, spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import { networkInterfaces } from 'node:os'
import path from 'node:path'
import { checkForUpdates, configureUpdater, installUpdate } from './updater'
import { checkPendingRollback, checkRollbackApplied, commitRollback, prepareRollback, triggerRollback } from './rollback'

const APP_NAME = 'XCAGI'

// 与 paths.py / 安装器太阳鸟种子目录一致（勿用 package.json 默认 xcagi-desktop）
// 注：单测环境通过 XCAGI_DESKTOP_TEST=1 跳过 bootstrap()，但模块顶层仍有副作用，
// 测试中通过 vi.mock('electron') 替换 app，故下列两行在测试环境下也安全。
app.setPath('userData', path.join(app.getPath('appData'), 'XCAGI'))
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required')

/** 桌面端统一使用 17500，避开 macOS AirPlay 与 Windows 本机常见 5000 端口冲突。 */
export function resolveDefaultDesktopPort(): number {
  const env = process.env.XCAGI_DESKTOP_PORT
  if (env) {
    const port = Number(env)
    if (Number.isFinite(port) && port > 0 && port < 65536) {
      return Math.floor(port)
    }
  }
  return 17500
}

export const DEFAULT_PORT = resolveDefaultDesktopPort()

/** 首选端口被占时自动尝试的备用端口数量（17500 → 17501…17509） */
export const PORT_FALLBACK_ATTEMPTS = 10

/** 运行时实际使用的端口：首选被占时可能落到备用端口 */
let activePort = DEFAULT_PORT

export function currentDesktopPort(): number {
  return activePort
}

export function setActiveDesktopPortForTests(port: number): void {
  activePort = port
}

/** 检测 127.0.0.1:port 是否可绑定（未被占用）。启动前必须预检。 */
export function isPortAvailable(port: number): Promise<boolean> {
  return new Promise(resolve => {
    const tester = net.createServer()
    tester.once('error', () => resolve(false))
    tester.once('listening', () => {
      tester.close(() => resolve(true))
    })
    tester.listen(port, '127.0.0.1')
  })
}

/** 首选端口被占时自动向后尝试备用端口；全部被占返回 null。 */
export async function resolveAvailableDesktopPort(
  preferred = DEFAULT_PORT,
  attempts = PORT_FALLBACK_ATTEMPTS
): Promise<number | null> {
  for (let i = 0; i < attempts; i++) {
    const candidate = preferred + i
    if (candidate >= 65536) break
    if (await isPortAvailable(candidate)) {
      return candidate
    }
  }
  return null
}

/** 首选与备用端口全部被占时给用户的引导文案。 */
export function portOccupiedHint(port: number): string {
  const airplayHint =
    port === 5000
      ? '\n\n5000 是历史开发端口，容易被系统服务或本机代理占用；正式桌面版默认端口为 17500。'
      : ''
  return (
    `本机端口 ${port}–${port + PORT_FALLBACK_ATTEMPTS - 1} 均被占用，XCAGI 无法启动本地服务。\n\n` +
    `请关闭占用这些端口的程序后重新打开 XCAGI。\n` +
    `（高级：也可设置环境变量 XCAGI_DESKTOP_PORT 指定其他端口。）` +
    airplayHint
  )
}

export type ProductSku = 'personal' | 'enterprise'

export const SKU_RUNTIME_EDITION: Record<ProductSku, string> = {
  personal: 'minimal',
  enterprise: 'full'
}

export const SKU_UPDATE_URL: Record<ProductSku, string> = {
  personal: 'https://update.xcagi.com/releases/stable/personal/',
  enterprise: 'https://update.xcagi.com/releases/stable/enterprise/'
}

/**
 * Ed25519 公钥（PEM），用于校验 update 元数据（latest.yml / latest-mac.yml）的二次签名。
 * 对应私钥存 GitHub Secrets: XCAGI_UPDATE_ED25519_PRIVATE_KEY（CI 签名用）。
 * 签名脚本: FHD/scripts/dev/sign_update_metadata.py
 */
export const ED25519_PUBLIC_KEY_PEM = [
  '-----BEGIN PUBLIC KEY-----',
  'MCowBQYDK2VwAyEAO6AeYJ05qwfSgpGR7+FZiL6cY0uGtSJVRqIiws3P6N8=',
  '-----END PUBLIC KEY-----'
].join('\n')

/** 企业版与网页 :5001 一致：完整侧栏，不强制 ?shell=1 */
export function desktopInitialUrl(): string {
  const base = `http://127.0.0.1:${currentDesktopPort()}/`
  if (readPackagedProductSku() === 'enterprise') {
    return base
  }
  return `${base}?shell=1`
}

export function readPackagedProductSku(): ProductSku | null {
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
      const raw = JSON.parse(readJsonTextFile(filePath)) as { sku?: string }
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

export function readJsonTextFile(filePath: string): string {
  const buffer = fs.readFileSync(filePath)
  let text: string
  if (buffer.length >= 2 && buffer[0] === 0xff && buffer[1] === 0xfe) {
    text = buffer.toString('utf16le')
  } else {
    text = buffer.toString('utf8')
  }
  return text.replace(/^\uFEFF/, '')
}

export function backendEditionEnv(): Record<string, string> {
  const sku = readPackagedProductSku()
  if (!sku) {
    // dev 模式未指定 SKU：默认 generic，与前端 generic 构建产物一致。
    // 显式注入 XCAGI_PRODUCT_SKU=generic 覆盖 XCAGI/.env 中可能的 enterprise 设置，
    // 避免前后端 SKU 不一致导致路由守卫误触发 admin 跳转。
    return {
      XCAGI_PRODUCT_SKU: 'generic',
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
let splashWindow: BrowserWindow | null = null
let backendProcess: ChildProcessWithoutNullStreams | null = null
let backendLogStream: fs.WriteStream | null = null
let tray: Tray | null = null
let restartCount = 0

/** 启动 splash 的内嵌 HTML（data URL，不依赖打包资源）。 */
export function splashHtml(): string {
  return [
    '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
    '<style>',
    'html,body{margin:0;height:100%;overflow:hidden;user-select:none;',
    'font-family:"Segoe UI","PingFang SC","Microsoft YaHei",system-ui,sans-serif;',
    'background:linear-gradient(135deg,#edf5fb 0%,#e7eef6 48%,#eef3f8 100%);}',
    '.wrap{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;}',
    '.logo{font-size:34px;font-weight:800;letter-spacing:.08em;color:#1d4ed8;}',
    '.bar{width:220px;height:4px;border-radius:999px;background:rgba(37,99,235,.15);overflow:hidden;}',
    '.bar i{display:block;height:100%;width:40%;border-radius:999px;background:#2563eb;',
    'animation:slide 1.2s ease-in-out infinite;}',
    '@keyframes slide{0%{transform:translateX(-100%)}100%{transform:translateX(320%)}}',
    '#phase{font-size:13px;color:#475569;min-height:18px;}',
    '.hint{font-size:11px;color:#94a3b8;}',
    '</style></head><body><div class="wrap">',
    '<div class="logo">XCAGI</div>',
    '<div class="bar"><i></i></div>',
    '<div id="phase">正在启动…</div>',
    '<div class="hint">首次启动需要初始化本地数据，可能耗时较长</div>',
    '</div></body></html>'
  ].join('')
}

/** 启动即出画面：主窗要等后端 health，splash 先让用户看到进程活着。 */
function createSplashWindow(): void {
  if (splashWindow) return
  try {
    splashWindow = new BrowserWindow({
      width: 380,
      height: 240,
      frame: false,
      resizable: false,
      maximizable: false,
      fullscreenable: false,
      show: false,
      alwaysOnTop: false,
      backgroundColor: '#eef3f8',
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true }
    })
    const icon = shellIconPath()
    if (fs.existsSync(icon)) {
      splashWindow.setIcon(nativeImage.createFromPath(icon))
    }
    splashWindow.on('closed', () => {
      splashWindow = null
    })
    void splashWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(splashHtml())}`)
    splashWindow.once('ready-to-show', () => splashWindow?.show())
  } catch {
    splashWindow = null
  }
}

/** 更新 splash 阶段文案（后端启动 → 等待服务就绪 → 加载界面）。 */
function setSplashPhase(text: string): void {
  const win = splashWindow
  if (!win || win.isDestroyed()) return
  const safe = JSON.stringify(text)
  void win.webContents
    .executeJavaScript(`(() => { const el = document.getElementById('phase'); if (el) el.textContent = ${safe}; })()`)
    .catch(() => { })
}

function closeSplashWindow(): void {
  const win = splashWindow
  splashWindow = null
  if (win && !win.isDestroyed()) {
    win.close()
  }
}

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
        String(currentDesktopPort()),
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
      String(currentDesktopPort()),
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

/** 须确认 uvicorn /api/health，避免 TCP 可达但不是 XCAGI 后端时误判就绪。 */
async function waitForBackendHealth(port: number, timeoutMs = packagedBackendHealthTimeoutMs()): Promise<void> {
  const started = Date.now()
  while (Date.now() - started <= timeoutMs) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`, {
        signal: AbortSignal.timeout(3_000)
      })
      const server = (response.headers.get('server') || '').toLowerCase()
      if (response.ok && server.includes('uvicorn')) {
        startupMarks.backendHealthMs = Date.now() - (startupMarks.backendSpawnMs ?? started)
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
    port === 5000
      ? ' 5000 是历史开发端口，正式桌面版默认端口为 17500；请清理 XCAGI_DESKTOP_PORT 后重启。'
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
  backendHealthMs?: number
  desktopStatusMs?: number
}

const startupMarks: DesktopStartupMarks = {}

export function readPackagedAppVersion(): string {
  if (!app.isPackaged) return 'dev'
  const candidates = [
    path.join(process.resourcesPath, 'backend', 'version.txt'),
    path.join(process.resourcesPath, 'product-sku.json')
  ]
  for (const filePath of candidates) {
    try {
      if (!fs.existsSync(filePath)) continue
      const raw = readJsonTextFile(filePath).trim()
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
export function readFrontendCacheKey(): string {
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

export function shouldClearFrontendCache(): boolean {
  const marker = path.join(app.getPath('userData'), 'frontend-cache-version.txt')
  const current = readFrontendCacheKey()
  try {
    const prev = fs.readFileSync(marker, 'utf8').trim()
    return prev !== current
  } catch {
    return true
  }
}

export function markFrontendCacheCleared(): void {
  const marker = path.join(app.getPath('userData'), 'frontend-cache-version.txt')
  fs.writeFileSync(marker, readFrontendCacheKey(), 'utf8')
}

/** 分阶段就绪：TCP 后即可出窗；desktop/status 软等待，不阻塞 60s 全量 Mod。 */
async function waitForBackendStatus(port: number, timeoutMs = 15_000): Promise<Record<string, unknown> | null> {
  const started = Date.now()
  while (Date.now() - started <= timeoutMs) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/desktop/status`)
      if (response.ok) {
        startupMarks.desktopStatusMs = Date.now() - (startupMarks.backendSpawnMs ?? started)
        return (await response.json()) as Record<string, unknown>
      }
    } catch {
      /* backend still importing routers */
    }
    await new Promise(resolve => setTimeout(resolve, 400))
  }
  console.warn(`[xcagi-desktop] /api/desktop/status 未在 ${timeoutMs}ms 内就绪，仍加载前端`)
  return null
}

/**
 * 检查启动自检 + 自动恢复状态，必要时弹窗提示用户。
 *
 * 后端启动时 recover_if_corrupt 会检测主库：
 * - action=ok：库健康，不弹
 * - action=restored：库损坏但已从备份恢复，弹警告（数据可能回退到上次备份）
 * - action=corrupt_no_backup：库损坏且无可用备份，弹错误（严重，可能丢失数据）
 */
async function showDbRecoveryDialogIfNeeded(status: Record<string, unknown> | null): Promise<void> {
  if (!status) return
  const recovery = status.dbRecovery as { action?: string; detail?: string | null } | undefined
  if (!recovery || recovery.action === 'ok') return

  if (recovery.action === 'corrupt_no_backup') {
    await dialog.showMessageBox({
      type: 'error',
      title: APP_NAME,
      message: '数据库损坏且无可用备份',
      detail:
        'XCAGI 启动时检测到数据库损坏，但未找到可用的备份文件。\n\n' +
        '应用仍会启动，但可能无法访问历史数据。请从菜单「导出诊断包」收集日志后联系技术支持。\n' +
        '建议尽快从外部备份（如 USB 备份）恢复 data/xcagi.db。'
    })
    return
  }

  if (recovery.action === 'restored') {
    const fromBackup = recovery.detail || '未知备份'
    await dialog.showMessageBox({
      type: 'warning',
      title: APP_NAME,
      message: '数据库已从备份自动恢复',
      detail:
        `XCAGI 启动时检测到数据库损坏，已自动从备份恢复：${fromBackup}\n\n` +
        '最近一次备份之后产生的数据可能丢失。请检查关键业务数据是否完整。\n' +
        '如需手动恢复更早的备份，请从菜单「打开数据目录」找到 backups/ 文件夹。'
    })
  }
}

async function startBackend(): Promise<void> {
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

  // 启动前预检：首选端口被占时自动尝试备用端口（17500…17509），
  // 全部被占才提示用户，避免后端起来即退出再触发无意义的自动重启。
  const resolvedPort = await resolveAvailableDesktopPort(DEFAULT_PORT)
  if (resolvedPort == null) {
    const hint = portOccupiedHint(DEFAULT_PORT)
    writeBackendLog(`[error] ports ${DEFAULT_PORT}..${DEFAULT_PORT + PORT_FALLBACK_ATTEMPTS - 1} occupied, abort backend spawn\n`)
    void dialog.showErrorBox(APP_NAME, hint)
    return
  }
  if (resolvedPort !== activePort) {
    writeBackendLog(`[port] preferred ${DEFAULT_PORT} occupied, falling back to ${resolvedPort}\n`)
    activePort = resolvedPort
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
      XCAGI_GLOBAL_RATE_LIMIT: '0',
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
    const uptimeMs = Date.now() - (startupMarks.backendSpawnMs ?? Date.now())
    writeBackendLog(`[exit] backend process exited code=${code} uptime=${uptimeMs}ms\n`)
    backendProcess = null
    if (app.isQuitting) {
      return
    }
    // 快速退出（< 5 秒）：通常是端口占用或配置错误，不自动重启以免浪费用户时间
    if (uptimeMs < 5000) {
      void dialog.showErrorBox(
        APP_NAME,
        `后端服务启动后立即退出（code=${code}）。\n\n请查看数据目录 logs/ 下后端日志，或从菜单导出诊断包。`
      )
      return
    }
    restartCount += 1
    if (restartCount <= 3) {
      setTimeout(() => void startBackend(), 1500)
      return
    }
    void dialog.showErrorBox(APP_NAME, `后端服务已退出（code=${code}），请重启 XCAGI。`)
  })
}

async function runBackendMigrationWithRollback(toVersion: string): Promise<void> {
  // 更新前的回滚准备：备份当前 backend，写入 marker
  // 这样更新后首次启动失败时可以自动还原
  try {
    await prepareRollback(toVersion)
  } catch (e) {
    // 备份失败不阻断更新（electron-updater 自身有重试机制）
    console.warn(`[xcagi-rollback] prepareRollback 失败，继续更新但不支持回滚: ${e instanceof Error ? e.message : e}`)
  }
  await runBackendMigration()
}

/** 触发回滚但吞掉自身错误，避免回滚失败导致二次崩溃 */
async function triggerRollbackSafe(reason: string): Promise<void> {
  try {
    await triggerRollback(reason)
    writeBackendLog(`[rollback] 已触发回滚：${reason}\n`)
  } catch (e) {
    writeBackendLog(`[rollback] 回滚失败：${e instanceof Error ? e.message : e}\n`)
  }
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
        XCAGI_GLOBAL_RATE_LIMIT: '0',
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

async function cookieHeaderForBackend(): Promise<string> {
  const url = `http://127.0.0.1:${currentDesktopPort()}/`
  const cookies = await session.defaultSession.cookies.get({ url })
  if (!cookies.length) {
    return ''
  }
  return cookies.map(c => `${c.name}=${c.value}`).join('; ')
}

async function exportSupportBundleInteractive(): Promise<void> {
  try {
    const cookie = await cookieHeaderForBackend()
    const headers: Record<string, string> = {}
    if (cookie) {
      headers.Cookie = cookie
    }
    const res = await fetch(`http://127.0.0.1:${currentDesktopPort()}/api/desktop/support-bundle`, {
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
    .catch(() => { })
}

export function isTrustedDesktopOrigin(rawUrl: string | undefined, expectedPort?: number): boolean {
  if (!rawUrl) return false
  try {
    const parsed = new URL(rawUrl)
    const hostAllowed = parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost'
    const port = expectedPort ?? currentDesktopPort()
    return parsed.protocol === 'http:' && hostAllowed && parsed.port === String(port)
  } catch {
    return false
  }
}

function configureDesktopMediaPermissions(): void {
  const ses = session.defaultSession
  ses.setPermissionRequestHandler((webContents, permission, callback, details) => {
    const mediaTypes = ((details as { mediaTypes?: string[] } | undefined)?.mediaTypes || [])
      .map(type => String(type))
    const wantsAudio =
      permission === 'media' &&
      (mediaTypes.length === 0 || mediaTypes.includes('audio') || mediaTypes.includes('microphone'))
    const requestUrl =
      (details as { requestingUrl?: string } | undefined)?.requestingUrl || webContents.getURL()
    callback(wantsAudio && isTrustedDesktopOrigin(requestUrl))
  })
  ses.setPermissionCheckHandler((webContents, permission, requestingOrigin, details) => {
    const mediaTypes = ((details as { mediaTypes?: string[] } | undefined)?.mediaTypes || [])
      .map(type => String(type))
    const wantsAudio =
      permission === 'media' &&
      (mediaTypes.length === 0 || mediaTypes.includes('audio') || mediaTypes.includes('microphone'))
    const origin = requestingOrigin || webContents?.getURL() || ''
    return wantsAudio && isTrustedDesktopOrigin(origin)
  })
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
  winOpts.show = false
  winOpts.backgroundColor = '#f4f7fb'
  mainWindow = new BrowserWindow(winOpts)
  if (process.platform !== 'darwin') {
    mainWindow.setAutoHideMenuBar(true)
    mainWindow.setMenuBarVisibility(false)
  }

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

  setSplashPhase('正在等待本地服务就绪…')
  await waitForBackendHealth(currentDesktopPort())
  setSplashPhase('正在加载界面…')

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

  // 防止渲染进程导航到本机后端以外的来源（electronegativity LimitNavigation HIGH）。
  // 桌面端只加载 127.0.0.1:{activePort}，任何外部跳转一律拦截。
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!isTrustedDesktopOrigin(url, currentDesktopPort())) {
      event.preventDefault()
      console.warn(`[xcagi-desktop] blocked will-navigate to ${url}`)
    }
  })
  // window.open / target=_blank 由系统浏览器打开，不在 Electron 内开新窗口。
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isTrustedDesktopOrigin(url, currentDesktopPort())) {
      return { action: 'allow' }
    }
    void shell.openExternal(url)
    return { action: 'deny' }
  })

  await mainWindow.loadURL(desktopInitialUrl(), {
    extraHeaders: 'Cache-Control: no-cache\r\n'
  })
  tagDesktopWebContents(mainWindow)
  if (process.platform === 'darwin') {
    ensureMacWindowInWorkArea(mainWindow)
  }
  closeSplashWindow()
  mainWindow.show()
  mainWindow.focus()

  void waitForBackendStatus(currentDesktopPort()).then(status => {
    console.info(
      '[xcagi-desktop] startup',
      JSON.stringify({
        ...startupMarks,
        desktopStatusOk: status !== null
      })
    )
    void showDbRecoveryDialogIfNeeded(status)
  })

  configureUpdater(mainWindow, runBackendMigrationWithRollback)
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
      { label: '导出诊断包…', click: () => void exportSupportBundleInteractive() },
      { label: '检查更新', click: () => void checkForUpdates() },
      { type: 'separator' },
      { label: '退出', click: () => app.quit() }
    ])
  )
}

function bootstrap(): void {
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
      // 主窗要等后端 health（首启可达 2–3 分钟），splash 让用户立即看到启动画面
      createSplashWindow()
      const sku = readPackagedProductSku()
      if (sku && !process.env.XCAGI_UPDATE_URL) {
        process.env.XCAGI_UPDATE_URL = SKU_UPDATE_URL[sku]
      }
      // 嵌入 Ed25519 公钥，启用 update 元数据二次签名校验
      if (!process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY) {
        process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY = ED25519_PUBLIC_KEY_PEM
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
        const port = currentDesktopPort()
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
      ipcMain.handle('xcagi:open-data-dir', () => shell.openPath(app.getPath('userData')))
      ipcMain.handle('xcagi:export-support-bundle', () => exportSupportBundleInteractive())
      ipcMain.handle('xcagi:check-for-updates', () => checkForUpdates())
      ipcMain.handle('xcagi:install-update', () => installUpdate(runBackendMigrationWithRollback))
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

      configureDesktopMediaPermissions()
      createMenu()
      createTray()

      // 更新后首次启动观察期：检查 rollback marker
      const pendingRollback = checkPendingRollback()
      if (pendingRollback) {
        writeBackendLog(`[rollback] 观察期：更新后首次启动 from=${pendingRollback.fromVersion} to=${pendingRollback.toVersion}\n`)
      }
      // 如果上次发生过回滚，提示用户
      const appliedRollback = checkRollbackApplied()
      if (appliedRollback) {
        void dialog.showMessageBox({
          type: 'info',
          title: APP_NAME,
          message: `XCAGI 已自动回滚到上一版本 ${appliedRollback.toVersion}`,
          detail: `原因：${appliedRollback.reason}\n\n当前版本仍可正常使用。如问题持续，请联系支持。`
        })
      }

      try {
        setSplashPhase('正在启动本地服务…')
        await startBackend()
        if (!backendProcess) {
          // 端口被占或后端可执行文件缺失，startBackend 已弹错误框
          // 如果是更新后首次启动，触发回滚
          closeSplashWindow()
          if (pendingRollback) {
            await triggerRollbackSafe('startBackend 失败：端口被占或 backend 可执行文件缺失')
            void dialog.showErrorBox(APP_NAME, '更新后启动失败，已自动回滚到上一版本。请重启 XCAGI。')
          }
          app.quit()
          return
        }
        try {
          await createWindow()
          // 启动成功：提交回滚（删除 marker，保留备份）
          if (pendingRollback) {
            commitRollback()
            writeBackendLog(`[rollback] 启动成功，已提交（marker 删除）\n`)
          }
        } catch (error) {
          const msg = error instanceof Error ? error.message : String(error)
          writeBackendLog(`[rollback] createWindow 失败: ${msg}\n`)
          closeSplashWindow()
          if (pendingRollback) {
            await triggerRollbackSafe(`createWindow 失败: ${msg}`)
            void dialog.showErrorBox(APP_NAME, '更新后窗口创建失败，已自动回滚到上一版本。请重启 XCAGI。')
          } else {
            void dialog.showErrorBox(APP_NAME, msg)
          }
          app.quit()
        }
      } catch (error) {
        // startBackend 或 waitForBackendHealth 抛错（health 超时）
        const msg = error instanceof Error ? error.message : String(error)
        writeBackendLog(`[rollback] startBackend 抛错: ${msg}\n`)
        closeSplashWindow()
        if (pendingRollback) {
          await triggerRollbackSafe(`后端启动失败: ${msg}`)
          void dialog.showErrorBox(APP_NAME, '更新后后端启动失败，已自动回滚到上一版本。请重启 XCAGI。')
        } else {
          void dialog.showErrorBox(APP_NAME, msg)
        }
        app.quit()
      }
    })

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        void createWindow()
      }
    })
  }
}

// 单测环境设置 XCAGI_DESKTOP_TEST=1 跳过启动逻辑，只测纯函数
if (!process.env.XCAGI_DESKTOP_TEST) {
  bootstrap()
}

declare global {
  namespace Electron {
    interface App {
      isQuitting?: boolean
    }
  }
}

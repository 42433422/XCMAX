import {
  BrowserWindow,
  Menu,
  Notification,
  Tray,
  app,
  crashReporter,
  dialog,
  ipcMain,
  nativeImage,
  screen,
  session,
  shell
} from 'electron'
import { ChildProcessWithoutNullStreams, execFile, execFileSync, spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import { networkInterfaces } from 'node:os'
import path from 'node:path'
import {
  configureUpdater,
  downloadUpdate,
  getUpdateStatus,
  installUpdate,
  readLocalBuildSha,
  runUpdateCheckWithDirectNet,
} from './updater'
import {
  attachDatabaseBackupToRollback,
  cancelPreparedRollback,
  checkPendingRollback,
  commitRollback,
  consumeRollbackApplied,
  prepareRollback,
  triggerRollback,
  type RollbackTriggerResult,
} from './rollback'
import { terminateChildProcess, waitForChildExit } from './backend-lifecycle'
import { clampWindowBounds, readWindowState, writeWindowState } from './window-state'
import { AutonomyController } from './autonomy/controller'
import { DesktopAutonomyAdapter } from './autonomy/desktop-adapter'
import { backendCrashPolicy } from './autonomy/policies/backend-crash.policy'
import { degradedRemediationPolicy } from './autonomy/policies/degraded-remediation.policy'
import { updateRollbackPolicy } from './autonomy/policies/update-rollback.policy'

const APP_NAME = 'XCAGI'
const KELLAI_BUNDLE_ID = 'com.kellai.desktop'
const POST_UPDATE_STABILITY_MS = 5_000

/** OTA / 更新站直连绕过（setProxy 用逗号；commandLine 用分号）。 */
export const OTA_PROXY_BYPASS_RULES =
  'xiu-ci.com,*.xiu-ci.com,update.xcagi.com,*.update.xcagi.com,localhost,127.0.0.1,<local>'

export function readWindowsInternetProxy(): string | null {
  if (process.platform !== 'win32') {
    return null
  }
  try {
    const enable = execFileSync(
      'reg',
      [
        'query',
        'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings',
        '/v',
        'ProxyEnable',
      ],
      { encoding: 'utf8', windowsHide: true },
    )
    if (!/0x1/.test(enable)) {
      return null
    }
    const server = execFileSync(
      'reg',
      [
        'query',
        'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings',
        '/v',
        'ProxyServer',
      ],
      { encoding: 'utf8', windowsHide: true },
    )
    const match = server.match(/ProxyServer\s+REG_SZ\s+(\S+)/)
    return match?.[1]?.trim() || null
  } catch {
    return null
  }
}

export function buildOtaPacScript(proxyServer: string): string {
  const proxy = proxyServer.replace(/'/g, '')
  return `
function FindProxyForURL(url, host) {
  if (host === 'xiu-ci.com' || dnsDomainIs(host, '.xiu-ci.com') ||
      host === 'update.xcagi.com' || dnsDomainIs(host, '.update.xcagi.com') ||
      host === 'localhost' || host === '127.0.0.1') {
    return 'DIRECT';
  }
  return 'PROXY ${proxy}; DIRECT';
}
`.trim()
}

export function parseProxyEndpoint(proxyServer: string): { host: string; port: number } | null {
  const raw = proxyServer.trim().replace(/^https?:\/\//i, '')
  const parts = raw.split(':')
  if (parts.length !== 2) {
    return null
  }
  const port = Number(parts[1])
  if (!parts[0] || !Number.isFinite(port) || port <= 0) {
    return null
  }
  return { host: parts[0], port: Math.floor(port) }
}

export function isProxyEndpointReachable(proxyServer: string, timeoutMs = 1500): Promise<boolean> {
  const endpoint = parseProxyEndpoint(proxyServer)
  if (!endpoint) {
    return Promise.resolve(false)
  }
  return new Promise(resolve => {
    const socket = net.connect({ host: endpoint.host, port: endpoint.port })
    const done = (ok: boolean) => {
      socket.removeAllListeners()
      socket.destroy()
      resolve(ok)
    }
    socket.setTimeout(timeoutMs)
    socket.once('connect', () => done(true))
    socket.once('timeout', () => done(false))
    socket.once('error', () => done(false))
  })
}

export function isProxyEndpointReachableSync(proxyServer: string, timeoutMs = 1200): boolean {
  const endpoint = parseProxyEndpoint(proxyServer)
  if (!endpoint) {
    return false
  }
  if (process.platform === 'win32') {
    try {
      const result = execFileSync(
        'powershell.exe',
        [
          '-NoProfile',
          '-Command',
          `(Test-NetConnection ${endpoint.host} -Port ${endpoint.port} -WarningAction SilentlyContinue).TcpTestSucceeded`,
        ],
        { encoding: 'utf8', timeout: timeoutMs + 800, windowsHide: true },
      ).trim()
      return result === 'True'
    } catch {
      return false
    }
  }
  return false
}

let systemProxyBypassMode: 'direct' | 'pac' | 'system' = 'system'

export function resolveSystemProxyBypassMode(): 'direct' | 'pac' | 'system' {
  return systemProxyBypassMode
}

export async function applyOtaProxyBypass(): Promise<void> {
  const proxyServer =
    readWindowsInternetProxy() ||
    String(process.env.HTTPS_PROXY || process.env.HTTP_PROXY || '').trim() ||
    null
  if (proxyServer) {
    const reachable = await isProxyEndpointReachable(proxyServer)
    if (!reachable) {
      systemProxyBypassMode = 'direct'
      await session.defaultSession.setProxy({ mode: 'direct' })
      return
    }
    systemProxyBypassMode = 'pac'
    await session.defaultSession.setProxy({
      pacScript: buildOtaPacScript(proxyServer),
    })
    return
  }
  systemProxyBypassMode = 'system'
  await session.defaultSession.setProxy({
    mode: 'system',
    proxyBypassRules: OTA_PROXY_BYPASS_RULES,
  })
}

// 与 paths.py / 安装器太阳鸟种子目录一致（勿用 package.json 默认 xcagi-desktop）
// 注：单测环境通过 XCAGI_DESKTOP_TEST=1 跳过 bootstrap()，但模块顶层仍有副作用，
// 测试中通过 vi.mock('electron') 替换 app，故下列两行在测试环境下也安全。
app.setPath('userData', path.join(app.getPath('appData'), 'XCAGI'))
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required')
// 系统代理（如 127.0.0.1:7890）未运行时，仍须直连更新站拉取 OTA 元数据与安装包。
app.commandLine.appendSwitch(
  'proxy-bypass-list',
  OTA_PROXY_BYPASS_RULES.replace(/,/g, ';')
)
if (process.env.XCAGI_DESKTOP_TEST !== '1') {
  const configuredProxy = readWindowsInternetProxy()
  if (configuredProxy && !isProxyEndpointReachableSync(configuredProxy)) {
    systemProxyBypassMode = 'direct'
    app.commandLine.appendSwitch('no-proxy-server')
  }
}

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

/** 桌面后端绑定地址：0.0.0.0 供手机同 WiFi 扫码；Electron UI 仍只加载 127.0.0.1。 */
export function resolveDesktopBackendBindHost(): string {
  const env = process.env.XCAGI_DESKTOP_API_HOST?.trim()
  if (env) {
    return env
  }
  return '0.0.0.0'
}

export const DESKTOP_BACKEND_BIND_HOST = resolveDesktopBackendBindHost()

/** 检测 bindHost:port 是否可绑定（未被占用）。桌面模式不做端口避让，启动前必须预检。 */
export function isPortAvailable(port: number, bindHost = DESKTOP_BACKEND_BIND_HOST): Promise<boolean> {
  return new Promise(resolve => {
    const tester = net.createServer()
    tester.once('error', () => resolve(false))
    tester.once('listening', () => {
      tester.close(() => resolve(true))
    })
    tester.listen(port, bindHost)
  })
}

/** 端口被占时给用户的引导文案。 */
export function portOccupiedHint(port: number): string {
  const airplayHint =
    port === 5000
      ? '\n\n5000 是历史开发端口，容易被系统服务或本机代理占用；正式桌面版默认端口为 17500。'
      : ''
  return (
    `端口 ${port} 已被占用，XCAGI 后端无法启动。\n\n` +
    `请关闭占用该端口的程序后重试，或设置环境变量 XCAGI_DESKTOP_PORT 指定其他端口后重启 XCAGI。` +
    airplayHint
  )
}

export type ProductSku = 'personal' | 'enterprise'

export const SKU_RUNTIME_EDITION: Record<ProductSku, string> = {
  personal: 'minimal',
  enterprise: 'full'
}

// update.xcagi.com 在部分网络解析到不可达 IP；发布产物实际由 xiu-ci.com 同源 /releases/ 提供。
export const SKU_UPDATE_URL: Record<ProductSku, string> = {
  personal: 'https://xiu-ci.com/releases/stable/personal/',
  enterprise: 'https://xiu-ci.com/releases/stable/enterprise/'
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
  const base = `http://127.0.0.1:${DEFAULT_PORT}/`
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

export function sanitizeBackendProxyEnv(
  env: NodeJS.ProcessEnv | Record<string, string | undefined>
): Record<string, string | undefined> {
  const next: Record<string, string | undefined> = { ...env }
  for (const key of ['ALL_PROXY', 'all_proxy'] as const) {
    const raw = String(next[key] || '').trim().toLowerCase()
    if (
      raw.startsWith('socks://') ||
      raw.startsWith('socks4://') ||
      raw.startsWith('socks5://') ||
      raw.startsWith('socks5h://')
    ) {
      // Prefer HTTP_PROXY for backend httpx; SOCKS needs optional socksio.
      delete next[key]
    }
  }
  // Chromium OTA bypass does not apply to the Python backend. Without NO_PROXY,
  // httpx sends market SSE (xiu-ci.com) through Clash/HTTP_PROXY and gets 502,
  // which surfaces as 流式对话首包超时.
  const bypass = OTA_PROXY_BYPASS_RULES.split(',')
    .map(s => s.trim())
    .filter(s => s && s !== '<local>')
  const existing = String(next.NO_PROXY || next.no_proxy || '')
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
  const merged = Array.from(new Set([...existing, ...bypass, '::1']))
  const joined = merged.join(',')
  next.NO_PROXY = joined
  next.no_proxy = joined
  return next
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
      XCAGI_DEFAULT_EDITION: 'generic',
      FHD_ETL_CENTER_ENABLED: process.env.FHD_ETL_CENTER_ENABLED || '0'
    }
  }
  const edition = SKU_RUNTIME_EDITION[sku]
  const env: Record<string, string> = {
    XCAGI_PRODUCT_SKU: sku,
    XCAGI_PLATFORM_SHELL: sku === 'enterprise' ? '0' : '1',
    XCAGI_DEFAULT_EDITION: edition,
    XCAGI_EDITION: edition,
    // 数据对接中心（通用 ETL）仅企业版默认开启；可用环境变量覆盖。
    FHD_ETL_CENTER_ENABLED:
      process.env.FHD_ETL_CENTER_ENABLED || (sku === 'enterprise' ? '1' : '0')
  }
  if (edition === 'minimal') {
    env.XCAGI_MINIMAL_EDITION = '1'
  } else if (edition === 'generic') {
    env.XCAGI_GENERIC_EDITION = '1'
  }
  return env
}

let mainWindow: BrowserWindow | null = null
let mainApplicationReady: Promise<void> | null = null
let rendererFailedDuringStartup = false
let backendProcess: ChildProcessWithoutNullStreams | null = null
let backendLogStream: fs.WriteStream | null = null
let tray: Tray | null = null
let restartCount = 0
let backendShutdownComplete = false
let backendShutdownPromise: Promise<void> | null = null

// 自治控制器（与现有更新观察期/backend 重启逻辑共存，零回归；阶段 1 接入）
let autonomyController: AutonomyController | null = null

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
        DESKTOP_BACKEND_BIND_HOST,
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
      DESKTOP_BACKEND_BIND_HOST,
      '--port',
      String(DEFAULT_PORT),
      '--data-dir',
      dataDir
    ],
    cwd: path.dirname(command)
  }
}

function rotateBackendLogIfNeeded(logPath: string): void {
  const maxBytes = 8 * 1024 * 1024
  try {
    if (!fs.existsSync(logPath)) {
      return
    }
    if (fs.statSync(logPath).size < maxBytes) {
      return
    }
    const rotated = `${logPath}.1`
    if (fs.existsSync(rotated)) {
      fs.unlinkSync(rotated)
    }
    fs.renameSync(logPath, rotated)
  } catch {
    /* ignore rotation failures */
  }
}

function ensureBackendLogStream(): fs.WriteStream | null {
  if (backendLogStream) {
    return backendLogStream
  }
  try {
    const logDir = path.join(app.getPath('userData'), 'logs')
    fs.mkdirSync(logDir, { recursive: true })
    const logPath = path.join(logDir, 'electron-backend.log')
    rotateBackendLogIfNeeded(logPath)
    backendLogStream = fs.createWriteStream(logPath, {
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

function initializeLocalCrashReporting(): void {
  try {
    const crashDir = path.join(app.getPath('userData'), 'crash-dumps')
    fs.mkdirSync(crashDir, { recursive: true })
    app.setPath('crashDumps', crashDir)
    crashReporter.start({ uploadToServer: false, compress: true })
    writeBackendLog(`[crash] local crash capture enabled dir=${crashDir}\n`)
  } catch (error) {
    writeBackendLog(`[crash] initialization failed: ${error instanceof Error ? error.message : String(error)}\n`)
  }
  process.on('uncaughtExceptionMonitor', error => {
    writeBackendLog(`[crash] main uncaughtException: ${error.stack || error.message}\n`)
  })
  process.on('unhandledRejection', reason => {
    writeBackendLog(`[crash] main unhandledRejection: ${reason instanceof Error ? reason.stack || reason.message : String(reason)}\n`)
  })
}

function packagedBackendHealthTimeoutMs(): number {
  if (!app.isPackaged) {
    return 60_000
  }
  // 首次启动：Alembic、Mod 种子、太阳鸟花名册等可能超过 60s
  return process.platform === 'win32' ? 180_000 : 120_000
}

/** 轻量就绪探测：/api/ping 无 NeuroBus 载荷，轮询更快。 */
export async function waitForBackendPing(
  port: number,
  timeoutMs = packagedBackendHealthTimeoutMs()
): Promise<void> {
  const started = Date.now()
  while (Date.now() - started <= timeoutMs) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/ping`, {
        signal: AbortSignal.timeout(2_000)
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
    await new Promise(resolve => setTimeout(resolve, 150))
  }
  const airplayHint =
    port === 5000
      ? ' 5000 是历史开发端口，正式桌面版默认端口为 17500；请清理 XCAGI_DESKTOP_PORT 后重启。'
      : ''
  const firstBootHint = app.isPackaged
    ? ' 若仍失败，请查看数据目录 logs/ 下后端日志，或从菜单导出诊断包。'
    : ''
  throw new Error(
    `后端 /api/ping 在 ${timeoutMs}ms 内未就绪（端口 ${port}）。${airplayHint}${firstBootHint}`
  )
}

/** @deprecated 使用 waitForBackendPing；保留别名供测试/旧引用。 */
export const waitForBackendHealth = waitForBackendPing

/** ping 就绪且业务路由已挂载（fast-start deferred 完成后）再加载主应用。 */
export async function waitForBackendApplicationReady(
  port: number,
  timeoutMs = packagedBackendHealthTimeoutMs(),
  options?: { skipPing?: boolean }
): Promise<void> {
  if (!options?.skipPing) {
    await waitForBackendPing(port, timeoutMs)
  }
  const started = Date.now()
  const remaining = () => Math.max(0, timeoutMs - (Date.now() - started))
  while (remaining() > 0) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/desktop/status`, {
        signal: AbortSignal.timeout(2_000)
      })
      if (response.ok) {
        const body = (await response.json()) as {
          appRoutesReady?: boolean
          readyForUi?: boolean
        }
        const routesReady = body.appRoutesReady ?? body.readyForUi
        if (routesReady !== false) {
          return
        }
      }
    } catch {
      /* routes still registering */
    }
    await new Promise(resolve => setTimeout(resolve, 150))
  }
  console.warn('[xcagi-desktop] appRoutesReady 未在时限内为 true，仍加载主应用')
}

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

  // 桌面模式不做端口避让：启动前预检 DEFAULT_PORT，被占则直接引导用户，避免后端
  // 启动后立即退出再触发无意义的自动重启。
  const portFree = await isPortAvailable(DEFAULT_PORT)
  if (!portFree) {
    const hint = portOccupiedHint(DEFAULT_PORT)
    writeBackendLog(`[error] port ${DEFAULT_PORT} occupied, abort backend spawn\n`)
    void dialog.showErrorBox(APP_NAME, hint)
    return
  }

  startupMarks.backendSpawnMs = Date.now()
  writeBackendLog(`[spawn] ${executable.command} ${executable.args.join(' ')}\n`)
  writeBackendLog(`[cwd] ${executable.cwd}\n`)
  backendProcess = spawn(executable.command, executable.args, {
    cwd: executable.cwd,
    env: {
      ...sanitizeBackendProxyEnv(process.env),
      XCAGI_DESKTOP_MODE: '1',
      XCAGI_DATA_DIR: app.getPath('userData'),
      XCAGI_API_HOST: DESKTOP_BACKEND_BIND_HOST,
      XCAGI_UVICORN_RELOAD: '0',
      XCAGI_GLOBAL_RATE_LIMIT: '0',
      LOG_LEVEL: process.env.LOG_LEVEL || (app.isPackaged ? 'WARNING' : 'INFO'),
      XCAGI_DESKTOP_FAST_START: '1',
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
    handleBackendSpawnError(error)
  })
  backendProcess.on('exit', code => {
    const uptimeMs = Date.now() - (startupMarks.backendSpawnMs ?? Date.now())
    writeBackendLog(`[exit] backend process exited code=${code} uptime=${uptimeMs}ms\n`)
    backendProcess = null
    if (app.isQuitting) {
      return
    }
    // 通知自治控制器 backend 退出（控制器据此追踪崩溃频率，5min ≥3 次则自动回滚）
    autonomyController?.ingest({
      source: 'backend_exit',
      kind: 'backend_exit',
      severity: 'crit',
      detail: `backend exited code=${code} uptime=${uptimeMs}ms`,
      ts: Date.now(),
      payload: { code, uptimeMs, restartCount },
    })
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
  try {
    await prepareRollback(toVersion)
    await runBackendMigration()
  } catch (error) {
    cancelPreparedRollback()
    throw error
  }
}

/** 触发回滚但吞掉自身错误，避免回滚失败导致二次崩溃 */
async function triggerRollbackSafe(reason: string): Promise<RollbackTriggerResult | null> {
  try {
    const result = await triggerRollback(reason)
    writeBackendLog(`[rollback] 已触发回滚 mode=${result.mode} scheduled=${result.scheduled}：${reason}\n`)
    return result
  } catch (e) {
    writeBackendLog(`[rollback] 回滚失败：${e instanceof Error ? e.message : e}\n`)
    return null
  }
}

function runBackendMigration(): Promise<string> {
  const executable = backendExecutable()
  return new Promise((resolve, reject) => {
    const child = spawn(executable.command, [...executable.args, '--migrate-only', '--backup'], {
      cwd: executable.cwd,
      env: {
        ...sanitizeBackendProxyEnv(process.env),
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
    let stdout = ''
    let databaseBackupPath = ''
    let backupAttachError: unknown
    child.stderr.on('data', data => {
      stderr += String(data)
      process.stderr.write(`[xcagi-migrate] ${data}`)
    })
    child.stdout.on('data', data => {
      stdout += String(data)
      process.stdout.write(`[xcagi-migrate] ${data}`)
      if (!databaseBackupPath) {
        const match = stdout.match(/^XCAGI_MIGRATION_BACKUP=(.+)$/m)
        const candidate = match?.[1]?.trim() || ''
        if (candidate) {
          try {
            attachDatabaseBackupToRollback(candidate)
            databaseBackupPath = candidate
          } catch (error) {
            backupAttachError = error
            child.kill()
          }
        }
      }
    })
    child.on('error', reject)
    child.on('exit', code => {
      if (backupAttachError) {
        reject(backupAttachError)
        return
      }
      if (code === 0) {
        resolve(databaseBackupPath)
      } else {
        reject(new Error(`数据库迁移失败（code=${code}）: ${stderr}`))
      }
    })
  })
}

async function cookieHeaderForBackend(): Promise<string> {
  const url = `http://127.0.0.1:${DEFAULT_PORT}/`
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
    const port = expectedPort ?? DEFAULT_PORT
    return parsed.protocol === 'http:' && hostAllowed && parsed.port === String(port)
  } catch {
    return false
  }
}

export function desktopWindowOpenAction(
  rawUrl: string,
  expectedPort = DEFAULT_PORT,
): 'allow' | 'deny' {
  return isTrustedDesktopOrigin(rawUrl, expectedPort) ? 'allow' : 'deny'
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

function openKellaiDesktop(): Promise<{ ok: boolean; reason?: string }> {
  if (process.platform !== 'darwin') {
    return shell
      .openExternal('kellai://messages?source=xcmax')
      .then(() => ({ ok: true }))
      .catch(error => ({ ok: false, reason: error instanceof Error ? error.message : String(error) }))
  }

  return new Promise(resolve => {
    execFile('open', ['-b', KELLAI_BUNDLE_ID], error => {
      if (!error) {
        resolve({ ok: true })
        return
      }
      resolve({ ok: false, reason: '未检测到客来来桌面端，请先安装并打开一次客来来。' })
    })
  })
}

async function stopBackend(): Promise<void> {
  const child = backendProcess
  backendProcess = null
  if (!child) {
    return
  }
  writeBackendLog(`[${new Date().toISOString()}] backend stop requested\n`)
  let result = 'already-exited'
  if (process.platform === 'win32' && child.pid) {
    const exited = waitForChildExit(child, 2500)
    await new Promise<void>(resolve => {
      execFile('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true }, () => resolve())
    })
    result = (await exited) ? 'killed' : 'kill-timeout'
  } else {
    result = await terminateChildProcess(child)
  }
  backendLogStream?.end(`[${new Date().toISOString()}] backend log closed result=${result}\n`)
  backendLogStream = null
}

async function createWindow(): Promise<void> {
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
  mainWindow = new BrowserWindow(winOpts)
  rendererFailedDuringStartup = false
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
  createdWindow.on('close', persistWindowState)
  if (process.platform !== 'darwin') {
    mainWindow.setAutoHideMenuBar(true)
    mainWindow.setMenuBarVisibility(false)
  }

  mainWindow.on('closed', () => {
    if (stateWriteTimer) clearTimeout(stateWriteTimer)
    mainWindow = null
    mainApplicationReady = null
  })
  if (process.platform === 'darwin') {
    mainWindow.on('leave-full-screen', () => {
      if (mainWindow) ensureMacWindowInWorkArea(mainWindow)
    })
    mainWindow.on('restore', () => {
      if (mainWindow) ensureMacWindowInWorkArea(mainWindow)
    })
  }

  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!isTrustedDesktopOrigin(url, DEFAULT_PORT) && !url.startsWith('file://') && !url.startsWith('data:')) {
      event.preventDefault()
      console.warn(`[xcagi-desktop] blocked will-navigate to ${url}`)
    }
  })
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    const action = desktopWindowOpenAction(url)
    if (action === 'deny') {
      console.warn(`[xcagi-desktop] blocked window open to ${url}`)
    }
    return { action }
  })
  mainWindow.webContents.on('unresponsive', () => {
    writeBackendLog('[crash] renderer unresponsive\n')
  })
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    writeBackendLog(`[crash] renderer gone reason=${details.reason} exitCode=${details.exitCode}\n`)
    if (checkPendingRollback()) {
      rendererFailedDuringStartup = true
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
    if (!mainWindow) {
      throw new Error('主窗口在应用加载前已关闭')
    }
    try {
      updateSplashProgress(92, '正在打开主界面…')
      await mainWindow.loadURL(desktopInitialUrl(), {
        extraHeaders: 'Cache-Control: no-cache\r\n'
      })
      tagDesktopWebContents(mainWindow)
      if (process.platform === 'darwin') {
        ensureMacWindowInWorkArea(mainWindow)
      }
      mainWindow.focus()
    } catch (error) {
      console.error('[xcagi-desktop] load main application failed', error)
      throw error
    }
  }

  const splashStarted = Date.now()
  const splashBudgetMs = packagedBackendHealthTimeoutMs()
  let splashPhase: 'boot' | 'routes' | 'done' = 'boot'
  let phaseStarted = splashStarted
  const splashTicker = setInterval(() => {
    if (!mainWindow || mainWindow.isDestroyed() || splashPhase === 'done') {
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

  const ready = waitForBackendPing(DEFAULT_PORT)
    .then(() => {
      splashPhase = 'routes'
      phaseStarted = Date.now()
      updateSplashProgress(58, '本地服务已就绪，正在加载业务模块…')
      return waitForBackendApplicationReady(DEFAULT_PORT, undefined, { skipPing: true })
    })
    .then(() => {
      splashPhase = 'done'
      updateSplashProgress(88, '正在加载应用…')
      return loadMainApplication()
    })
  mainApplicationReady = ready
  void ready
    .catch(error => {
      console.error('[xcagi-desktop] backend readiness wait failed', error)
      splashPhase = 'done'
      updateSplashProgress(100, '启动失败，请查看日志', { error: true })
      if (!checkPendingRollback()) {
        void dialog.showErrorBox(APP_NAME, error instanceof Error ? error.message : String(error))
      }
    })
    .finally(() => clearInterval(splashTicker))

  mainWindow.webContents.on('did-finish-load', () => {
    if (mainWindow) tagDesktopWebContents(mainWindow)
  })

  void waitForBackendStatus(DEFAULT_PORT).then(status => {
    console.info(
      '[xcagi-desktop] startup',
      JSON.stringify({
        ...startupMarks,
        desktopStatusOk: status !== null
      })
    )
    void showDbRecoveryDialogIfNeeded(status)
  })

  configureUpdater(mainWindow)
}

async function waitForMainApplicationReady(): Promise<void> {
  if (!mainApplicationReady) {
    throw new Error('主界面就绪任务未初始化')
  }
  await mainApplicationReady
}

async function waitForPostUpdateStartupStability(
  durationMs = POST_UPDATE_STABILITY_MS,
): Promise<void> {
  const deadline = Date.now() + durationMs
  while (Date.now() < deadline) {
    if (!backendProcess) {
      throw new Error('更新后观察期内 backend 进程退出')
    }
    if (!mainWindow || mainWindow.isDestroyed()) {
      throw new Error('更新后观察期内主窗口退出')
    }
    if (rendererFailedDuringStartup) {
      throw new Error('更新后观察期内 renderer 进程崩溃')
    }
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  await waitForBackendPing(DEFAULT_PORT, 5_000)
}

function createMenu(): void {
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

function createTray(): void {
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
      { label: '检查更新', click: () => void runUpdateCheckWithDirectNet() },
      { type: 'separator' },
      { label: '退出', click: () => app.quit() }
    ])
  )
}

function handleBackendSpawnError(error: Error): void {
  backendProcess = null
  writeBackendLog(`[error] backend spawn failed: ${error.message}\n`)
  if (app.isQuitting) {
    return
  }
  void dialog.showErrorBox(
    APP_NAME,
    `后端服务启动失败：${error.message}\n\n应用将退出，请重启 XCAGI。`,
  )
  app.quit()
}

function bootstrap(): void {
  const gotLock = app.requestSingleInstanceLock()
  if (!gotLock) {
    app.quit()
  } else {
    initializeLocalCrashReporting()
    app.on('second-instance', () => {
      if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore()
        mainWindow.focus()
      }
    })

    app.on('before-quit', () => {
      app.isQuitting = true
    })

    // will-quit runs after BrowserWindows have closed, so renderer keep-alive
    // connections no longer prevent the backend from shutting down gracefully.
    app.on('will-quit', event => {
      if (backendShutdownComplete) {
        return
      }
      event.preventDefault()
      if (!backendShutdownPromise) {
        backendShutdownPromise = stopBackend().finally(() => {
          backendShutdownComplete = true
          app.quit()
        })
      }
    })

    app.whenReady().then(async () => {
      await applyOtaProxyBypass()
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
      ipcMain.handle('xcagi:open-kellai-desktop', () => openKellaiDesktop())
      ipcMain.handle('xcagi:export-support-bundle', () => exportSupportBundleInteractive())
      ipcMain.handle('xcagi:check-for-updates', () => runUpdateCheckWithDirectNet())
      ipcMain.handle('xcagi:get-update-status', () => getUpdateStatus())
      ipcMain.handle('xcagi:download-update', () => downloadUpdate())
      ipcMain.handle('xcagi:install-update', () =>
        installUpdate(runBackendMigrationWithRollback, cancelPreparedRollback),
      )
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
      const appliedRollback = consumeRollbackApplied()
      if (appliedRollback) {
        void dialog.showMessageBox({
          type: 'info',
          title: APP_NAME,
          message: `XCAGI 已自动回滚到上一版本 ${appliedRollback.toVersion}`,
          detail: `原因：${appliedRollback.reason}\n\n当前版本仍可正常使用。如问题持续，请联系支持。`
        })
      }

      try {
        // 先出 Splash，再并行拉起后端，避免用户长时间无窗口反馈
        await createWindow()
        updateSplashProgress(12, '正在连接本地服务…')
        await startBackend()
        if (!backendProcess) {
          // 端口被占或后端可执行文件缺失，startBackend 已弹错误框
          // 如果是更新后首次启动，触发回滚
          if (pendingRollback) {
            const rollback = await triggerRollbackSafe('startBackend 失败：端口被占或 backend 可执行文件缺失')
            void dialog.showErrorBox(
              APP_NAME,
              !rollback
                ? '更新后启动失败，自动回滚也未能启动。请从官网下载稳定版重新安装。'
                : rollback.scheduled
                  ? '更新后启动失败，正在恢复上一版本；XCAGI 将自动重启。'
                  : '更新后启动失败，已恢复上一版本。请重启 XCAGI。',
            )
          }
          app.quit()
          return
        }
        if (pendingRollback) {
          await waitForMainApplicationReady()
          await waitForPostUpdateStartupStability()
          commitRollback()
          writeBackendLog(`[rollback] 后端、业务路由、主界面与观察期就绪，已提交（marker 删除）\n`)
        }
        // 启动自治控制器（与现有更新观察期/backend 重启逻辑共存，零回归）
        // 控制器提供新增能力：5min 内 backend 崩溃 ≥3 次自动回滚、磁盘满自动清日志、配置漂移自动纠正
        try {
          const adapter = new DesktopAutonomyAdapter({
            backendProcessRef: () => {
              if (!backendProcess) return null
              const pid = backendProcess.pid ?? null
              const startedAt = startupMarks.backendSpawnMs ?? null
              return { pid, running: true, startedAt }
            },
            restartCountRef: () => restartCount,
            port: DEFAULT_PORT,
            appVersion: app.getVersion(),
            buildSha: readLocalBuildSha(),
            configPath: null,
            // Phase 1：注入 backend 重启 / 版本回滚闭包（与 main.ts 现有逻辑共存）
            // restartBackend 调用 startBackend()；backend exit 时 backendProcess 已被清空，可直接 spawn
            restartBackend: async () => { await startBackend() },
            // triggerRollback 复用现有 triggerRollbackSafe 吞错语义
            triggerRollback: async () => { await triggerRollbackSafe('autonomy_controller_triggered') },
            // knownGoodConfigContent 当前为 null（main.ts 暂无配置文件概念，repair_config 自动拒绝）
            knownGoodConfigContent: null,
          })
          autonomyController = new AutonomyController(
            adapter,
            [backendCrashPolicy, degradedRemediationPolicy, updateRollbackPolicy],
            {
              enabled: !process.env.XCAGI_DESKTOP_TEST,
              pollIntervalMs: 5_000,
            },
          )
          autonomyController.start()
          writeBackendLog(`[autonomy] controller started\n`)
        } catch (e) {
          writeBackendLog(`[autonomy] controller start failed: ${e instanceof Error ? e.message : e}\n`)
        }
      } catch (error) {
        const msg = error instanceof Error ? error.message : String(error)
        writeBackendLog(`[rollback] 桌面启动失败: ${msg}\n`)
        if (pendingRollback) {
          const rollback = await triggerRollbackSafe(`桌面启动失败: ${msg}`)
          void dialog.showErrorBox(
            APP_NAME,
            !rollback
              ? '更新后启动失败，自动回滚也未能启动。请从官网下载稳定版重新安装。'
              : rollback.scheduled
                ? '更新后启动失败，正在恢复上一版本；XCAGI 将自动重启。'
                : msg.includes('createWindow') || msg.includes('窗口')
                  ? '更新后窗口创建失败，已恢复上一版本。请重启 XCAGI。'
                  : '更新后后端启动失败，已恢复上一版本。请重启 XCAGI。',
          )
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

export const __test_only = {
  createTray,
  handleBackendSpawnError,
}

declare global {
  namespace Electron {
    interface App {
      isQuitting?: boolean
    }
  }
}

import { app } from 'electron'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { readJsonTextFile } from './backend-env-utils'

export const APP_NAME = 'XCAGI'

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
  ['MCowBQYD', 'K2VwAyEA', 'O6AeYJ05', 'qwfSgpGR', '7+FZiL6c', 'Y0uGtSJV', 'RqIiws3P', '6N8='].join(''),
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

export function repoRoot(): string {
  return app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '..', '..')
}

/** 托盘与窗口图标：与 dist 同级打包的 resources（由 beforePack 生成）。 */
export function shellIconPath(): string {
  const name = process.platform === 'win32' ? 'icon.ico' : 'icon.png'
  return path.join(__dirname, '..', 'resources', name)
}

export function packagedBackendCandidates(): string[] {
  const backendDir = path.join(process.resourcesPath, 'backend')
  const exe = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
  return [
    path.join(backendDir, exe),
    path.join(backendDir, 'xcagi-backend', exe),
    path.join(backendDir, '_internal', exe)
  ]
}

export function findPackagedBackendExecutable(): string {
  const candidates = packagedBackendCandidates()
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate
    }
  }
  return candidates[0]
}

export function backendExecutable(): { command: string; args: string[]; cwd: string } {
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

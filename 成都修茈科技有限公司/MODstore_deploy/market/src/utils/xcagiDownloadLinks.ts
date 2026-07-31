export type XcagiProductSku = 'personal' | 'enterprise'
export type XcagiDownloadPlatform = 'win' | 'mac' | 'android'
/** macOS 安装包 CPU 架构（与 COS 文件名 *-mac-{arch}.dmg 一致） */
export type XcagiMacArch = 'x64' | 'arm64'

// 对外稳定产品版本与 VERSION.md 一致；工具链内部三段版本不用于官网下载文件名。
export const DEFAULT_XCAGI_DOWNLOAD_VERSION = '1.0.0.1'
export const DEFAULT_XCAGI_ANDROID_VERSION = '1.0.0.1'

// 官方下载清单 manifest.json URL（CI 自动生成，含 SHA256 + size）
// 失败时降级到 normalizeXcagiDownloadBase + xcagiDownloadUrl 静态生成
export const OFFICIAL_MANIFEST_URL = `https://xiu-ci.com/xcagi-v${DEFAULT_XCAGI_DOWNLOAD_VERSION}/manifest.json`

export interface XcagiDownloadManifestEntry {
  url: string
  filename: string
  sha256: string
  size: number
  arch?: XcagiMacArch
  platform_label?: string
}

export interface XcagiDownloadManifestChannel {
  base_url: string
  personal?: {
    win?: XcagiDownloadManifestEntry
    mac?: XcagiDownloadManifestEntry[]
    android?: XcagiDownloadManifestEntry
  }
  enterprise?: {
    win?: XcagiDownloadManifestEntry
    mac?: XcagiDownloadManifestEntry[]
    android?: XcagiDownloadManifestEntry
  }
}

export interface XcagiDownloadManifest {
  schema: string
  version: string
  release_ready?: boolean
  generated_at: string
  git_sha: string
  channels: {
    auto_update: XcagiDownloadManifestChannel
    official_download: XcagiDownloadManifestChannel
  }
}

let cachedManifest: XcagiDownloadManifest | null = null
let manifestFetchPromise: Promise<XcagiDownloadManifest | null> | null = null

/**
 * 拉取官方下载清单 manifest.json。
 * - 成功:返回 manifest 并缓存
 * - 失败:返回 null,调用方降级到 xcagiDownloadUrl() 静态生成
 * - 并发去重:同一时刻只发一个请求
 */
export async function fetchDownloadManifest(
  manifestUrl: string = OFFICIAL_MANIFEST_URL,
  options: { force?: boolean } = {},
): Promise<XcagiDownloadManifest | null> {
  if (options.force) {
    cachedManifest = null
    manifestFetchPromise = null
  }
  if (cachedManifest) return cachedManifest
  if (manifestFetchPromise) return manifestFetchPromise

  manifestFetchPromise = (async () => {
    try {
      const resp = await fetch(manifestUrl, {
        method: 'GET',
        cache: 'no-cache',
        signal: AbortSignal.timeout(8000),
      })
      if (!resp.ok) {
        console.warn(`[xcagiDownloadLinks] manifest fetch failed: HTTP ${resp.status} from ${manifestUrl}`)
        return null
      }
      const data = (await resp.json()) as XcagiDownloadManifest
      if (data?.schema !== 'xcagi.download_manifest/v1') {
        console.warn(`[xcagiDownloadLinks] manifest schema mismatch: ${data?.schema}`)
        return null
      }
      cachedManifest = data
      return data
    } catch (err) {
      console.warn(`[xcagiDownloadLinks] manifest fetch error:`, err)
      return null
    } finally {
      manifestFetchPromise = null
    }
  })()

  return manifestFetchPromise
}

/**
 * 从 manifest 中查找指定 SKU + 平台 + 架构的下载 entry。
 * 返回 null 表示 manifest 未加载或无对应 entry(调用方应降级)。
 */
export function findManifestEntry(
  manifest: XcagiDownloadManifest | null,
  sku: XcagiProductSku,
  platform: XcagiDownloadPlatform,
  macArch: XcagiMacArch = 'arm64',
): XcagiDownloadManifestEntry | null {
  if (!manifest) return null
  const channel = manifest.channels.official_download
  const skuEntry = channel[sku]
  if (!skuEntry) return null

  if (platform === 'win') return skuEntry.win ?? null
  if (platform === 'android') return skuEntry.android ?? null
  if (platform === 'mac') {
    const macs = skuEntry.mac
    if (!macs || macs.length === 0) return null
    return macs.find((m) => m.arch === macArch) ?? macs[0] ?? null
  }
  return null
}

/**
 * 解析下载 URL:优先从 manifest 获取(含 SHA256 + size),降级到静态生成。
 * 返回 entry(含 url/sha256/size)或仅 url 字符串。
 */
export async function resolveDownloadEntry(
  sku: XcagiProductSku,
  platform: XcagiDownloadPlatform,
  options: {
    base?: string
    version?: string
    androidVersion?: string
    macArch?: XcagiMacArch
    manifestUrl?: string
  } = {},
): Promise<XcagiDownloadManifestEntry> {
  const macArch = options.macArch ?? detectMacDownloadArch()
  const manifest = await fetchDownloadManifest(options.manifestUrl)
  const entry = findManifestEntry(manifest, sku, platform, macArch)
  if (entry) return entry

  // 降级:静态生成 URL,无 SHA256/size
  const base = normalizeXcagiDownloadBase(options.base, options.version)
  const version = options.version ?? DEFAULT_XCAGI_DOWNLOAD_VERSION
  const androidVersion = options.androidVersion ?? DEFAULT_XCAGI_ANDROID_VERSION
  const filename = xcagiDownloadFileName(sku, platform, version, androidVersion, macArch)
  return {
    url: xcagiDownloadUrl(sku, platform, base, version, androidVersion, macArch),
    filename,
    sha256: '',
    size: 0,
  }
}

export function normalizeXcagiDownloadBase(
  base: string | undefined,
  version = DEFAULT_XCAGI_DOWNLOAD_VERSION,
): string {
  return (base || `https://xiu-ci.com/xcagi-v${version}`).replace(/\/$/, '')
}

export function xcagiDownloadFileName(
  sku: XcagiProductSku,
  platform: XcagiDownloadPlatform,
  version = DEFAULT_XCAGI_DOWNLOAD_VERSION,
  androidVersion = DEFAULT_XCAGI_ANDROID_VERSION,
  macArch: XcagiMacArch = 'arm64',
): string {
  const label = sku === 'personal' ? 'Personal' : 'Enterprise'
  if (platform === 'android') return `XCAGI-${label}-Android-${androidVersion}.apk`
  if (platform === 'mac') return `XCAGI-${label}-${version}-mac-${macArch}.dmg`
  return `XCAGI-${label}-Setup-${version}-x64.exe`
}

export function xcagiDownloadUrl(
  sku: XcagiProductSku,
  platform: XcagiDownloadPlatform,
  base: string,
  version = DEFAULT_XCAGI_DOWNLOAD_VERSION,
  androidVersion = DEFAULT_XCAGI_ANDROID_VERSION,
  macArch: XcagiMacArch = 'arm64',
): string {
  return `${base}/${sku}/${xcagiDownloadFileName(sku, platform, version, androidVersion, macArch)}`
}

/** 从 URL 查询参数读取 mac 架构覆盖（?macArch=arm64|x64，便于测试） */
export function macArchFromQuery(): XcagiMacArch | null {
  if (typeof window === 'undefined') return null
  const raw = new URLSearchParams(window.location.search).get('macArch')?.toLowerCase()
  if (raw === 'arm64' || raw === 'aarch64') return 'arm64'
  if (raw === 'x64' || raw === 'x86_64' || raw === 'intel') return 'x64'
  return null
}

/**
 * 为下载页选择 macOS dmg 架构：优先 URL 覆盖，其次 Client Hints / WebGL，默认 arm64（Apple Silicon）。
 */
export function detectMacDownloadArch(): XcagiMacArch {
  const fromQuery = macArchFromQuery()
  if (fromQuery) return fromQuery

  if (typeof navigator === 'undefined') return 'arm64'

  const ua = navigator.userAgent
  if (/\b(aarch64|arm64)\b/i.test(ua)) return 'arm64'

  if (typeof document !== 'undefined') {
    try {
      const canvas = document.createElement('canvas')
      const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
      if (gl && 'getExtension' in gl) {
        const ext = (gl as WebGLRenderingContext).getExtension('WEBGL_debug_renderer_info')
        if (ext) {
          const renderer = String((gl as WebGLRenderingContext).getParameter(ext.UNMASKED_RENDERER_INFO))
          if (/Apple M\d|Apple GPU/i.test(renderer)) return 'arm64'
        }
      }
    } catch {
      /* ignore */
    }
  }

  const nav = navigator as Navigator & {
    userAgentData?: { platform?: string; architecture?: string }
  }
  if (nav.userAgentData?.architecture === 'arm') return 'arm64'
  if (nav.userAgentData?.architecture === 'x86') return 'x64'

  return 'arm64'
}

export function macDownloadArchLabel(arch: XcagiMacArch): string {
  return arch === 'arm64' ? 'Apple Silicon' : 'Intel'
}

export type XcagiProductSku = 'personal' | 'enterprise'
export type XcagiDownloadPlatform = 'win' | 'mac' | 'android'
/** macOS 安装包 CPU 架构（与 COS 文件名 *-mac-{arch}.dmg 一致） */
export type XcagiMacArch = 'x64' | 'arm64'

// 全产品线 v10 锁：官网下载/安装包锚点与 VERSION.md 一致，恒 10.0.0（见 FHD/VERSION.md L41/L45）。
// 不在此写死历史版本（8.1.0 等）；如需按 release_train 覆盖，用构建期 VITE_XCAGI_DOWNLOAD_VERSION。
export const DEFAULT_XCAGI_DOWNLOAD_VERSION = '10.0.0'
export const DEFAULT_XCAGI_ANDROID_VERSION = '10.0.0'

export function normalizeXcagiDownloadBase(
  base: string | undefined,
  version = DEFAULT_XCAGI_DOWNLOAD_VERSION,
): string {
  return (base || `https://dl.xiu-ci.com/xcagi-v${version}`).replace(/\/$/, '')
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
  // macOS artifacts live under SKU-specific directories, so the file name itself is SKU-neutral.
  if (platform === 'mac') return `XCAGI-${version}-mac-${macArch}.dmg`
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

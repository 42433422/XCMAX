import { session } from 'electron'
import { DEFAULT_PORT } from './desktop-config'
import { isTrustedDesktopOrigin } from './desktop-navigation'

/**
 * 媒体权限（麦克风/音频）仅放行可信本地 origin。
 * 语音输入与语音转写依赖 media 权限；其他 origin 一律拒绝。
 */
export function configureDesktopMediaPermissions(): void {
  const ses = session.defaultSession
  ses.setPermissionRequestHandler((webContents, permission, callback, details) => {
    const mediaTypes = ((details as { mediaTypes?: string[] } | undefined)?.mediaTypes || [])
      .map(type => String(type))
    const wantsAudio =
      permission === 'media' &&
      (mediaTypes.length === 0 || mediaTypes.includes('audio') || mediaTypes.includes('microphone'))
    const requestUrl =
      (details as { requestingUrl?: string } | undefined)?.requestingUrl || webContents.getURL()
    callback(wantsAudio && isTrustedDesktopOrigin(requestUrl, DEFAULT_PORT))
  })
  ses.setPermissionCheckHandler((webContents, permission, requestingOrigin, details) => {
    const mediaTypes = ((details as { mediaTypes?: string[] } | undefined)?.mediaTypes || [])
      .map(type => String(type))
    const wantsAudio =
      permission === 'media' &&
      (mediaTypes.length === 0 || mediaTypes.includes('audio') || mediaTypes.includes('microphone'))
    const origin = requestingOrigin || webContents?.getURL() || ''
    return wantsAudio && isTrustedDesktopOrigin(origin, DEFAULT_PORT)
  })
}

/**
 * 桌面端 CSP 纵深防御兜底。
 *
 * 常规路径：后端（XCAGI_DESKTOP_MODE=1）已在 SecurityHeadersMiddleware 为本地方向
 * 注入 CSP 头（见 app/middleware/security_headers.py）。Electron 主进程看不到 HTTP
 * 响应头，electronegativity 因此误报 CSP_GLOBAL_CHECK。
 *
 * 本模块在 Electron 层做兜底：仅当响应自带 CSP 且资源是可信任本地主文档时，才注入
 * 一份与后端桌面模式一致的 CSP。若后端已注入则原样保留，绝不叠加多个 CSP header
 * —— 浏览器会取多个 CSP 的交集（更严格），叠加易导致 SPA 脚本/字体/WebSocket 被误拦。
 */
const DESKTOP_FALLBACK_CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "img-src 'self' data: blob:",
  "font-src 'self' data: https://fonts.gstatic.com",
  "connect-src 'self' ws: wss: http: https:",
  "frame-ancestors 'self'",
  "base-uri 'self'",
  "object-src 'none'",
].join('; ')

/**
 * 纯函数：判定是否为主文档注入兜底 CSP。
 * 仅当（1）响应未自带 CSP、（2）是主文档、（3）URL 为可信本地 origin 时注入。
 * 返回需要设置的 header 值，无需注入则返回 null。
 */
export function resolveDesktopCspInjection(input: {
  responseHeaders?: Record<string, string[]>
  resourceType?: string
  url?: string
  expectedPort?: number
}): string | null {
  const { responseHeaders, resourceType, url, expectedPort } = input
  const headers = responseHeaders ?? {}
  const hasExistingCsp = Object.entries(headers).some(
    ([key, values]) =>
      key.toLowerCase() === 'content-security-policy' &&
      (values || []).some(value => String(value).includes('default-src')),
  )
  if (
    hasExistingCsp ||
    (resourceType && resourceType !== 'mainFrame') ||
    !isTrustedDesktopOrigin(url, expectedPort ?? DEFAULT_PORT)
  ) {
    return null
  }
  return DESKTOP_FALLBACK_CSP
}

export function installDesktopCspDefenseInDepth(): void {
  const ses = session.defaultSession
  ses.webRequest.onHeadersReceived((details, callback) => {
    const headers = details.responseHeaders ?? {}
    const csp = resolveDesktopCspInjection({
      responseHeaders: headers,
      resourceType: details.resourceType,
      url: details.url,
    })
    if (csp) {
      headers['Content-Security-Policy'] = [csp]
    }
    callback({ responseHeaders: headers })
  })
}

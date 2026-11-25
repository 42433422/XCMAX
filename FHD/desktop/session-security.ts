import { session } from 'electron'
import { DEFAULT_PORT } from './desktop-config'
import { isTrustedDesktopOrigin } from './desktop-navigation'

/** Explicit audio-only requests from the trusted desktop main frame. */
export function isAllowedDesktopMedia(input: {
  permission: string
  topUrl: string
  requestUrl: string
  details?: { mediaTypes?: string[]; mediaType?: string; isMainFrame?: boolean }
}): boolean {
  const { permission, topUrl, requestUrl, details } = input
  const mediaTypes = details?.mediaTypes ?? (details?.mediaType ? [details.mediaType] : [])
  return permission === 'media' && details?.isMainFrame !== false &&
    Array.isArray(mediaTypes) && mediaTypes.length > 0 &&
    mediaTypes.every(type => type === 'audio' || type === 'microphone') &&
    isTrustedDesktopOrigin(topUrl, DEFAULT_PORT) &&
    isTrustedDesktopOrigin(requestUrl, DEFAULT_PORT)
}

/** 媒体权限仅放行可信本地音频，未知或视频请求默认拒绝。 */
export function configureDesktopMediaPermissions(): void {
  const ses = session.defaultSession
  ses.setPermissionRequestHandler((webContents, permission, callback, details) => {
    callback(isAllowedDesktopMedia({ permission, topUrl: webContents.getURL(), requestUrl: details.requestingUrl || webContents.getURL(), details }))
  })
  ses.setPermissionCheckHandler((webContents, permission, requestingOrigin, details) => {
    return isAllowedDesktopMedia({ permission, topUrl: webContents?.getURL() || '', requestUrl: requestingOrigin, details })
  })
}

/**
 * 可信本地主文档没有 CSP 时才注入后端桌面策略。
 * 已有策略（包括仅含 script-src 的策略及多个策略）原样保留，避免放宽响应的限制。
 */
const DESKTOP_FALLBACK_CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "img-src 'self' data: blob:",
  "media-src 'self' data:",
  "font-src 'self' data: https://fonts.gstatic.com",
  "frame-src 'self' blob:",
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
      (values || []).some(value => String(value).trim().length > 0),
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

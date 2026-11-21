import { session, type Session } from 'electron'
import { DEFAULT_PORT } from './desktop-config'
import { isTrustedDesktopOrigin } from './desktop-navigation'
import { desktopWorkspaceToken } from './backend-env'
import { isTrustedIpcSender } from './ipc-sender-guard'
import { desktopRuntime, hasVerifiedDesktopBackend } from './runtime-state'

/** Authenticate the anonymous local workspace without disclosing the token to JS. */
export function installDesktopWorkspaceCapability(ses: Session = session.defaultSession): void {
  // All URLs must be intercepted: redirects must not carry a capability off-origin.
  ses.webRequest.onBeforeSendHeaders((details, callback) => {
    const headers = { ...details.requestHeaders }
    for (const name of Object.keys(headers)) {
      if (name.toLowerCase() === 'x-xcagi-workspace-capability') delete headers[name]
    }
    try {
      const target = new URL(details.url)
      if (hasVerifiedDesktopBackend() && details.resourceType === 'xhr'
        && !target.username && !target.password
        && target.pathname.startsWith('/api/local-workspace/')
        && isTrustedDesktopOrigin(target.href, DEFAULT_PORT)
        && details.frame && target.origin === new URL(details.frame.url).origin
        && isTrustedIpcSender(
          { sender: { id: details.webContentsId ?? -1 }, senderFrame: details.frame },
          desktopRuntime.mainWindow,
          { port: DEFAULT_PORT, splashUrl: '' },
          [...desktopRuntime.auxiliaryWindows],
        )) {
        headers['X-XCAGI-Workspace-Capability'] = desktopWorkspaceToken
      }
    } catch { /* A destroyed frame or invalid URL never receives a capability. */ }
    callback({ requestHeaders: headers })
  })
}

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

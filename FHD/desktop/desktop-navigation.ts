export function isTrustedDesktopOrigin(rawUrl: string | undefined, expectedPort: number): boolean {
  if (!rawUrl) return false
  try {
    const url = new URL(rawUrl)
    const host = url.hostname.toLowerCase()
    const trustedHost = host === '127.0.0.1' || host === 'localhost'
    if (!trustedHost || url.protocol !== 'http:') return false
    return url.port === String(expectedPort)
  } catch {
    return false
  }
}

export function desktopWindowOpenAction(rawUrl: string, expectedPort: number): 'allow' | 'deny' {
  return isTrustedDesktopOrigin(rawUrl, expectedPort) ? 'allow' : 'deny'
}

export function isTrustedDesktopExternalUrl(rawUrl: string | undefined): boolean {
  if (!rawUrl) return false
  try {
    const url = new URL(rawUrl)
    const host = url.hostname.toLowerCase()
    return url.protocol === 'https:' && (host === 'xiu-ci.com' || host.endsWith('.xiu-ci.com'))
  } catch {
    return false
  }
}

export function handleDesktopWindowOpen(
  rawUrl: string,
  expectedPort: number,
  openExternal: (url: string) => Promise<unknown>,
  warn: (message: string) => void,
): 'allow' | 'deny' {
  if (isTrustedDesktopExternalUrl(rawUrl)) {
    void openExternal(rawUrl).catch(error => {
      warn(`[xcagi-desktop] failed to open trusted external URL: ${error instanceof Error ? error.message : String(error)}`)
    })
    return 'deny'
  }
  const action = desktopWindowOpenAction(rawUrl, expectedPort)
  if (action === 'deny') warn(`[xcagi-desktop] blocked window open to ${rawUrl}`)
  return action
}

/**
 * Chromium may abort the first navigation while the local backend redirects
 * from splash to the SPA. If the same trusted desktop page is already loaded,
 * treating that transient abort as a boot failure produces a false error dialog.
 */
export function isBenignDesktopLoadAbort(
  error: unknown,
  currentUrl: string | undefined,
  expectedPort: number,
): boolean {
  const message = error instanceof Error ? error.message : String(error || '')
  return /ERR_ABORTED/i.test(message) && isTrustedDesktopOrigin(currentUrl, expectedPort)
}

const DEEP_LINK_SCHEME = 'xcagi://'

/**
 * 从进程启动参数中提取自定义协议深链（Windows/Linux 通过 second-instance argv 收到）。
 * 例如 `xcagi://chat?q=...`。未命中返回 null。
 */
export function findDeepLinkArg(argv: string[] | undefined | null): string | null {
  if (!argv || !Array.isArray(argv) || argv.length === 0) return null
  const found = argv.find(arg => typeof arg === 'string' && arg.startsWith(DEEP_LINK_SCHEME))
  return found || null
}

export interface ParsedDesktopDeepLink {
  raw: string
  host: string
  path: string
  params: Record<string, string>
}

/**
 * 解析深链为结构化对象，供渲染端路由与透传原始 URL。
 * 任何解析失败都返回 null（调用方应安全降级为「仅唤起窗口」）。
 */
export function parseDesktopDeepLink(raw: string | undefined | null): ParsedDesktopDeepLink | null {
  if (!raw || typeof raw !== 'string' || !raw.startsWith(DEEP_LINK_SCHEME)) return null
  try {
    const url = new URL(raw)
    const params: Record<string, string> = {}
    url.searchParams.forEach((value, key) => {
      params[key] = value
    })
    return { raw, host: url.hostname, path: url.pathname, params }
  } catch {
    return null
  }
}

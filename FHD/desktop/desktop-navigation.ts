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

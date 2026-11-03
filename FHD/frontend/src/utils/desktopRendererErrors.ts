/** Page-world crash capture. Preload runs in an isolated world and often sees an empty ErrorEvent. */

type DesktopErrorApi = {
  reportError?: (payload: { type: string; error: string; stack?: string; source?: string }) => void
}

function desktopApi(): DesktopErrorApi | null {
  const host = window as Window & { xcagiDesktop?: DesktopErrorApi }
  return host.xcagiDesktop?.reportError ? host.xcagiDesktop : null
}

function textOf(value: unknown): string {
  if (value instanceof Error) return value.message || value.name
  if (typeof value === 'string') return value
  if (value == null) return ''
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

export function installDesktopRendererErrorReporting(): void {
  if (typeof window === 'undefined' || !desktopApi()) return
  window.addEventListener('error', (event) => {
    const err = event.error
    const source = [event.filename, event.lineno, event.colno].filter((part) => part !== undefined && part !== '').join(':')
    const target = event.target as { tagName?: string; src?: string; href?: string } | null
    const resource = target && target !== window ? `${target.tagName || 'resource'} ${target.src || target.href || ''}`.trim() : ''
    desktopApi()?.reportError?.({
      type: 'renderer:error',
      error: textOf(err) || String(event.message || '').trim() || resource || 'renderer error without message',
      stack: err instanceof Error ? err.stack : undefined,
      source: source || undefined,
    })
  })
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason
    desktopApi()?.reportError?.({
      type: 'renderer:unhandledrejection',
      error: textOf(reason) || 'unhandled rejection without reason',
      stack: reason instanceof Error ? reason.stack : undefined,
    })
  })
}

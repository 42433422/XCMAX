/** Page-world crash capture. Preload runs in an isolated world and often sees an empty ErrorEvent. */

type DesktopErrorApi = {
  reportError?: (payload: { type: string; error: string; stack?: string; source?: string }) => void
}

function desktopApi(): DesktopErrorApi | null {
  const host = window as Window & { xcagiDesktop?: DesktopErrorApi }
  return host.xcagiDesktop?.reportError ? host.xcagiDesktop : null
}

function usableText(value: unknown): string {
  const text = typeof value === 'string' ? value.trim() : ''
  return text && text !== 'unknown' ? text : ''
}

function stackLine(stack?: string): string {
  if (!stack) return ''
  const line = stack.split('\n').map(part => part.trim()).find(Boolean) || ''
  return line.replace(/^Error:\s*/, '')
}

/** Pull message and stack off Error and cross-realm error-like objects. Never emit the placeholder "unknown". */
export function describeRendererFault(value: unknown): { error: string; stack?: string } {
  if (value instanceof Error) {
    const stack = value.stack
    return { error: usableText(value.message) || usableText(value.name) || stackLine(stack), stack }
  }
  if (value && typeof value === 'object') {
    const record = value as { message?: unknown; name?: unknown; stack?: unknown }
    const stack = typeof record.stack === 'string' ? record.stack : undefined
    const error = usableText(record.message) || usableText(record.name) || stackLine(stack)
    if (error || stack) return { error, stack }
  }
  if (typeof value === 'string') return { error: usableText(value) }
  if (value == null) return { error: '' }
  try {
    return { error: JSON.stringify(value) }
  } catch {
    return { error: String(value) }
  }
}

export function reportDesktopRendererFault(value: unknown, source?: string, type = 'renderer:error'): void {
  const described = describeRendererFault(value)
  const where = usableText(source)
  desktopApi()?.reportError?.({
    type,
    error: described.error || where || 'renderer error without message',
    stack: described.stack,
    source: where || undefined,
  })
}

export function installDesktopRendererErrorReporting(): void {
  if (typeof window === 'undefined' || !desktopApi()) return
  window.addEventListener('error', (event) => {
    const err = event.error
    const source = [event.filename, event.lineno, event.colno].filter((part) => part !== undefined && part !== '').join(':')
    const target = event.target as { tagName?: string; src?: string; href?: string } | null
    const resource = target && target !== window ? `${target.tagName || 'resource'} ${target.src || target.href || ''}`.trim() : ''
    const described = describeRendererFault(err)
    desktopApi()?.reportError?.({
      type: 'renderer:error',
      error: described.error || usableText(event.message) || resource || 'renderer error without message',
      stack: described.stack,
      source: source || undefined,
    })
  })
  window.addEventListener('unhandledrejection', (event) => {
    const described = describeRendererFault(event.reason)
    desktopApi()?.reportError?.({
      type: 'renderer:unhandledrejection',
      error: described.error || 'unhandled rejection without reason',
      stack: described.stack,
    })
  })
}

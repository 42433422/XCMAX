import { afterEach, describe, expect, it, vi } from 'vitest'
import { installDesktopRendererErrorReporting } from './desktopRendererErrors'

type Report = { type: string; error: string; stack?: string; source?: string }

function install(reportError = vi.fn()) {
  const spy = vi.spyOn(window, 'addEventListener').mockImplementation((type, listener, options) => {
    listeners.push({ type: String(type), listener: listener as EventListener })
    return nativeAddEventListener(type, listener as EventListener, options)
  })
  Object.defineProperty(window, 'xcagiDesktop', { configurable: true, value: { reportError } })
  installDesktopRendererErrorReporting()
  spy.mockRestore()
  return reportError
}

const listeners: Array<{ type: string; listener: EventListener }> = []
const nativeAddEventListener = window.addEventListener.bind(window)

describe('desktop renderer error reporting', () => {
  afterEach(() => {
    for (const item of listeners) window.removeEventListener(item.type, item.listener)
    listeners.length = 0
    Object.defineProperty(window, 'xcagiDesktop', { configurable: true, value: undefined })
  })

  it('does nothing until the desktop host can accept a report', () => {
    installDesktopRendererErrorReporting()
    window.dispatchEvent(new ErrorEvent('error', { message: 'ignored' }))
  })

  it('reports an Error, a string, a resource, and a value that cannot be serialized', () => {
    const reportError = install()
    const failure = new Error('page exploded')
    window.dispatchEvent(new ErrorEvent('error', { error: failure, message: 'page exploded', filename: 'app.js', lineno: 4, colno: 2 }))
    window.dispatchEvent(new ErrorEvent('error', { message: 'script failed', filename: 'boot.js', lineno: 1, colno: 1 }))

    const image = document.createElement('img')
    image.src = 'https://example.test/mark.png'
    const resource = new Event('error')
    Object.defineProperty(resource, 'target', { value: image })
    Object.defineProperty(resource, 'message', { value: '' })
    window.dispatchEvent(resource)

    const circular: { self?: unknown } = {}
    circular.self = circular
    const opaque = new Event('error')
    Object.defineProperty(opaque, 'error', { value: circular })
    Object.defineProperty(opaque, 'message', { value: '' })
    window.dispatchEvent(opaque)

    const reports = reportError.mock.calls.map(([payload]) => payload as Report)
    expect(reports.map((item) => item.type)).toEqual(['renderer:error', 'renderer:error', 'renderer:error', 'renderer:error'])
    expect(reports[0]).toMatchObject({ error: 'page exploded', source: 'app.js:4:2' })
    expect(reports[0].stack).toContain('page exploded')
    expect(reports[1].error).toBe('script failed')
    expect(reports[2].error).toContain('IMG')
    expect(reports[2].error).toContain('mark.png')
    expect(reports[3].error).toBe('[object Object]')
  })

  it('reports an error-like object message and does not persist a bare unknown', () => {
    const reportError = install()
    const crossRealm = { message: 'workspace gate failed', stack: 'Error: workspace gate failed\n at boot' }
    window.dispatchEvent(new ErrorEvent('error', { error: crossRealm, message: 'unknown' }))
    const onlyUnknown = { message: 'unknown', stack: 'Error: session probe failed\n at refresh' }
    const opaque = new Event('error')
    Object.defineProperty(opaque, 'error', { value: onlyUnknown })
    Object.defineProperty(opaque, 'message', { value: 'unknown' })
    window.dispatchEvent(opaque)
    const reports = reportError.mock.calls.map(([payload]) => payload as Report)
    expect(reports[0]).toMatchObject({ error: 'workspace gate failed' })
    expect(reports[0].stack).toContain('workspace gate failed')
    expect(reports[1].error).toBe('session probe failed')
    expect(reports.map(item => item.error)).not.toContain('unknown')
  })

  it('reports unhandled rejections with and without a reason', () => {
    const reportError = install()
    const reason = new Error('rejected')
    const withReason = new Event('unhandledrejection')
    Object.defineProperty(withReason, 'reason', { value: reason })
    window.dispatchEvent(withReason)
    const empty = new Event('unhandledrejection')
    Object.defineProperty(empty, 'reason', { configurable: true, value: null })
    window.dispatchEvent(empty)
    const reports = reportError.mock.calls.map(([payload]) => payload as Report)
    expect(reports).toEqual([
      expect.objectContaining({
        type: 'renderer:unhandledrejection',
        error: 'rejected',
        stack: expect.stringContaining('rejected'),
      }),
      {
        type: 'renderer:unhandledrejection',
        error: 'unhandled rejection without reason',
        stack: undefined,
      },
    ])
  })
})

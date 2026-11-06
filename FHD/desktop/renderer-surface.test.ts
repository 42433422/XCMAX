import type { BrowserWindow } from 'electron'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { attachRendererSurfaceRecovery, bitmapLooksUniformBlank } from './renderer-surface'

describe('bitmapLooksUniformBlank', () => {
  it('matches the unmapped-window white frame (mean about 245, std 0)', () => {
    const bitmap = new Uint8Array(64)
    bitmap.fill(245)
    expect(bitmapLooksUniformBlank(bitmap)).toBe(true)
  })

  it('accepts a normal painted client area', () => {
    const bitmap = new Uint8Array(64)
    for (let i = 0; i < bitmap.length; i += 4) {
      bitmap[i] = i % 8 === 0 ? 20 : 240
      bitmap[i + 1] = 80
      bitmap[i + 2] = 140
      bitmap[i + 3] = 255
    }
    expect(bitmapLooksUniformBlank(bitmap)).toBe(false)
    expect(bitmapLooksUniformBlank(new Uint8Array())).toBe(false)
  })
})

describe('attachRendererSurfaceRecovery', () => {
  afterEach(() => vi.useRealTimers())
  function host(platform: NodeJS.Platform = 'linux') {
    const listeners = new Map<string, Array<(...args: unknown[]) => void>>()
    const winListeners = new Map<string, Array<() => void>>()
    const reload = vi.fn()
    const win = {
      isDestroyed: vi.fn(() => false),
      isVisible: () => true,
      on: (event: string, listener: () => void) => {
        winListeners.set(event, [...(winListeners.get(event) || []), listener])
      },
      webContents: {
        on: (event: string, listener: (...args: unknown[]) => void) => {
          listeners.set(event, [...(listeners.get(event) || []), listener])
        },
        isLoadingMainFrame: vi.fn(() => false),
        capturePage: vi.fn(async () => ({ toBitmap: () => new Uint8Array([20, 80, 140, 255]) })),
        reload,
        invalidate: vi.fn(),
        setBackgroundThrottling: vi.fn(),
      },
    }
    const log = vi.fn()
    attachRendererSurfaceRecovery(win as unknown as BrowserWindow, log, platform)
    return { win, listeners, winListeners, reload, log }
  }

  async function paintedHost() {
    vi.useFakeTimers()
    const h = host()
    h.listeners.get('did-finish-load')?.[0]()
    await vi.advanceTimersByTimeAsync(350)
    h.win.webContents.capturePage.mockResolvedValue({ toBitmap: () => new Uint8Array(32).fill(245) })
    return h
  }

  it('requires two blank captures after a previously painted page and never loops', async () => {
    const { winListeners, listeners, reload, log } = await paintedHost()
    winListeners.get('show')?.[0]()
    await vi.advanceTimersByTimeAsync(350)
    expect(reload).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(350)
    expect(reload).toHaveBeenCalledOnce()
    expect(log.mock.calls.map((call) => String(call[0])).join('')).toContain('reloading in place')
    listeners.get('did-finish-load')?.[0]()
    await vi.advanceTimersByTimeAsync(3500)
    winListeners.get('restore')?.[0]()
    await vi.advanceTimersByTimeAsync(3500)
    expect(reload).toHaveBeenCalledOnce()
  })

  it('leaves slow initial navigation and an unpainted loading page alone', async () => {
    vi.useFakeTimers()
    const { win, winListeners, listeners, reload } = host()
    win.webContents.capturePage.mockResolvedValue({ toBitmap: () => new Uint8Array(32).fill(245) })
    winListeners.get('show')?.[0]()
    await vi.advanceTimersByTimeAsync(5000)
    expect(win.webContents.capturePage).not.toHaveBeenCalled()
    listeners.get('did-finish-load')?.[0]()
    await vi.advanceTimersByTimeAsync(5000)
    expect(reload).not.toHaveBeenCalled()
  })

  it.each(['empty', 'rejected'])('does not treat an %s screenshot as a blank compositor', async (capture) => {
    const { win, winListeners, reload } = await paintedHost()
    if (capture === 'empty') win.webContents.capturePage.mockResolvedValue({ toBitmap: () => new Uint8Array() })
    else win.webContents.capturePage.mockRejectedValue(new Error('capture unavailable'))
    winListeners.get('restore')?.[0]()
    await vi.advanceTimersByTimeAsync(1500)
    expect(reload).not.toHaveBeenCalled()
  })

  it.each(['closed', 'navigation'])('retires pending captures on %s', async (event) => {
    const { win, listeners, winListeners, reload } = await paintedHost()
    let resolve!: (image: Awaited<ReturnType<typeof win.webContents.capturePage>>) => void
    win.webContents.capturePage.mockImplementation(() => new Promise(done => { resolve = done }))
    winListeners.get('show')?.[0]()
    await vi.advanceTimersByTimeAsync(350)
    if (event === 'closed') winListeners.get('closed')?.[0]()
    else listeners.get('did-start-loading')?.[0]()
    resolve({ toBitmap: () => new Uint8Array(32).fill(245) })
    await vi.advanceTimersByTimeAsync(1000)
    expect(reload).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('limits automatic compositor probing to Linux', async () => {
    vi.useFakeTimers()
    const { win, listeners, winListeners } = host('darwin')
    listeners.get('did-finish-load')?.[0]()
    winListeners.get('show')?.[0]()
    await vi.advanceTimersByTimeAsync(1000)
    expect(win.webContents.capturePage).not.toHaveBeenCalled()
  })

  it('reloads from the main process on Ctrl+R even when the renderer is not painting', () => {
    const { listeners, reload } = host()
    const event = { preventDefault: vi.fn() }
    listeners.get('before-input-event')?.[0](event, { type: 'keyDown', key: 'r', control: true })
    expect(event.preventDefault).toHaveBeenCalledOnce()
    expect(reload).toHaveBeenCalledOnce()
  })

  it('does not reload twice inside the 3s guard', () => {
    const { listeners, reload, log } = host()
    const fire = () => listeners.get('unresponsive')?.[0]()
    fire()
    fire()
    expect(reload).toHaveBeenCalledOnce()
    expect(log.mock.calls.map((call) => String(call[0])).join('')).toContain('skip reload')
  })
})

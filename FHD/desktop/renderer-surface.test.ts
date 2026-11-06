import { describe, expect, it, vi } from 'vitest'
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
  })
})

describe('attachRendererSurfaceRecovery', () => {
  function host() {
    const listeners = new Map<string, Array<(...args: unknown[]) => void>>()
    const winListeners = new Map<string, Array<() => void>>()
    const reload = vi.fn()
    const win = {
      isDestroyed: () => false,
      isVisible: () => true,
      on: (event: string, listener: () => void) => {
        winListeners.set(event, [...(winListeners.get(event) || []), listener])
      },
      webContents: {
        on: (event: string, listener: (...args: unknown[]) => void) => {
          listeners.set(event, [...(listeners.get(event) || []), listener])
        },
        capturePage: vi.fn(async () => ({ toBitmap: () => new Uint8Array(32).fill(245) })),
        reload,
        invalidate: vi.fn(),
        setBackgroundThrottling: vi.fn(),
      },
    }
    const log = vi.fn()
    attachRendererSurfaceRecovery(win, log)
    return { win, listeners, winListeners, reload, log }
  }

  it('reloads a uniform blank frame after the window is shown, without quitting', async () => {
    vi.useFakeTimers()
    const { winListeners, reload, log } = host()
    winListeners.get('show')?.[0]()
    await vi.advanceTimersByTimeAsync(350)
    expect(reload).toHaveBeenCalledOnce()
    expect(log.mock.calls.map((call) => String(call[0])).join('')).toContain('reloading in place')
    vi.useRealTimers()
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

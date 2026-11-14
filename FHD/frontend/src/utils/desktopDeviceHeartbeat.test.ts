import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { installDesktopDeviceHeartbeat } from './desktopDeviceHeartbeat'
import { LS_ENTERPRISE_SESSION_HINT } from './authSessionCache'

/** 心跳只对已登录会话上报；用本地会话标记模拟登录态（不含任何凭据）。 */
function markSignedIn(): void {
  window.localStorage.setItem(LS_ENTERPRISE_SESSION_HINT, String(Date.now()))
}

describe('installDesktopDeviceHeartbeat', () => {
  const originalFetch = global.fetch

  beforeEach(() => {
    window.localStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.restoreAllMocks()
    global.fetch = originalFetch
  })

  it('registers a stable device id and repeats every minute', async () => {
    markSignedIn()
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    global.fetch = fetchMock as unknown as typeof fetch

    installDesktopDeviceHeartbeat()
    await vi.advanceTimersByTimeAsync(0)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    const body = JSON.parse(String(init?.body))
    expect(body.device_id).toBeTruthy()
    expect(window.localStorage.getItem('xcagi.desktop.device_id')).toBe(body.device_id)

    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('reuses the persisted device id instead of generating a new one', async () => {
    markSignedIn()
    window.localStorage.setItem('xcagi.desktop.device_id', 'device-1')
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    global.fetch = fetchMock as unknown as typeof fetch

    installDesktopDeviceHeartbeat()
    await vi.advanceTimersByTimeAsync(0)

    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(body.device_id).toBe('device-1')
  })

  it('skips the heartbeat when storage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage blocked')
    })
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    installDesktopDeviceHeartbeat()
    await vi.advanceTimersByTimeAsync(0)

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('does not report a heartbeat while signed out', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    installDesktopDeviceHeartbeat()
    await vi.advanceTimersByTimeAsync(120_000)

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('skips the heartbeat when only the device id cannot be stored', async () => {
    markSignedIn()
    const original = Storage.prototype.getItem
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, key: string) {
      if (key === 'xcagi.desktop.device_id') throw new Error('storage blocked')
      return original.call(this, key)
    })
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    installDesktopDeviceHeartbeat()
    await vi.advanceTimersByTimeAsync(0)

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('logs a genuine service failure but not an expired session', async () => {
    markSignedIn()
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 }) as unknown as typeof fetch
    installDesktopDeviceHeartbeat()
    await vi.advanceTimersByTimeAsync(0)
    expect(warn).not.toHaveBeenCalled()

    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500 }) as unknown as typeof fetch
    await vi.advanceTimersByTimeAsync(60_000)
    expect(warn).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['MacIntel', 'macos'],
    ['Win32', 'windows'],
    ['Linux x86_64', 'linux'],
    ['iPhone', 'desktop'],
  ])('reports the platform label for %s', async (platform, expected) => {
    markSignedIn()
    vi.spyOn(window.navigator, 'platform', 'get').mockReturnValue(platform)
    vi.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue('Electron/39 XCAGI')
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    global.fetch = fetchMock as unknown as typeof fetch

    installDesktopDeviceHeartbeat()
    await vi.advanceTimersByTimeAsync(0)

    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(body.platform).toBe(expected)
    expect(body.label).toBe('XCAGI 桌面端')
  })

  it('ignores transient heartbeat failures', async () => {
    markSignedIn()
    global.fetch = vi.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch

    installDesktopDeviceHeartbeat()
    await vi.advanceTimersByTimeAsync(0)

    expect(window.localStorage.getItem('xcagi.desktop.device_id')).toBeTruthy()
  })
})

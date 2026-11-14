import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { installDesktopDeviceHeartbeat } from './desktopDeviceHeartbeat'

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

  it('ignores transient heartbeat failures', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch

    installDesktopDeviceHeartbeat()
    await vi.advanceTimersByTimeAsync(0)

    expect(window.localStorage.getItem('xcagi.desktop.device_id')).toBeTruthy()
  })
})

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { connectRealtime, disconnectRealtime } from './realtimeClient'

vi.mock('./infrastructure/storage/tokenStore', () => ({
  getAccessToken: vi.fn(),
}))

import { getAccessToken } from './infrastructure/storage/tokenStore'

const mockGetAccessToken = vi.mocked(getAccessToken)

describe('realtimeClient', () => {
  let mockWs: any

  beforeEach(() => {
    vi.useFakeTimers()
    mockGetAccessToken.mockReturnValue('test-token')
    disconnectRealtime(true)

    mockWs = {
      onopen: null as (() => void) | null,
      onmessage: null as ((ev: { data: string }) => void) | null,
      onerror: null as (() => void) | null,
      onclose: null as (() => void) | null,
      readyState: 0,
      send: vi.fn(),
      close: vi.fn(),
      OPEN: 1,
    }

    const wsRef = mockWs
    const WsFn = vi.fn(function (this: any) {
      return wsRef
    })
    WsFn.OPEN = 1
    vi.stubGlobal('WebSocket', WsFn)
  })

  afterEach(() => {
    vi.useRealTimers()
    disconnectRealtime(true)
  })

  it('does not connect when no token', () => {
    mockGetAccessToken.mockReturnValue(null)
    connectRealtime()
    expect(WebSocket).not.toHaveBeenCalled()
  })

  it('creates WebSocket with correct URL when token exists', () => {
    connectRealtime()
    expect(WebSocket).toHaveBeenCalledWith(
      expect.stringContaining('/api/realtime/ws?token=test-token'),
    )
  })

  it('uses wss protocol on https page', () => {
    Object.defineProperty(window, 'location', {
      value: { protocol: 'https:', host: 'example.com' },
      writable: true,
      configurable: true,
    })
    connectRealtime()
    expect(WebSocket).toHaveBeenCalledWith(expect.stringContaining('wss://'))
    Object.defineProperty(window, 'location', {
      value: { protocol: 'http:', host: 'localhost' },
      writable: true,
      configurable: true,
    })
  })

  it('invokes notification handler on notification message', () => {
    const handler = vi.fn()
    connectRealtime(handler)
    mockWs.onmessage!({ data: JSON.stringify({ type: 'notification' }) })
    expect(handler).toHaveBeenCalled()
  })

  it('does not invoke handler on non-notification message', () => {
    const handler = vi.fn()
    connectRealtime(handler)
    mockWs.onmessage!({ data: JSON.stringify({ type: 'ping' }) })
    expect(handler).not.toHaveBeenCalled()
  })

  it('handles invalid JSON gracefully', () => {
    const handler = vi.fn()
    connectRealtime(handler)
    mockWs.onmessage!({ data: 'not-json' })
    expect(handler).not.toHaveBeenCalled()
  })

  it('sends ping on interval when connected', () => {
    connectRealtime()
    mockWs.readyState = 1
    mockWs.onopen!()
    vi.advanceTimersByTime(50_000)
    expect(mockWs.send).toHaveBeenCalledWith(
      expect.stringContaining('"type":"ping"'),
    )
  })

  it('replaces existing connection on reconnect', () => {
    connectRealtime()
    const firstWs = mockWs
    const secondWs = { ...firstWs, close: vi.fn() }
    mockWs = secondWs
    vi.stubGlobal('WebSocket', vi.fn(() => secondWs))
    connectRealtime()
    expect(firstWs.close).toHaveBeenCalledWith(1000, 'replaced')
  })

  it('disconnectRealtime closes socket and clears handler', () => {
    connectRealtime(vi.fn())
    disconnectRealtime(true)
    expect(mockWs.close).toHaveBeenCalledWith(1000, 'client')
  })

  it('schedules reconnect on close when token exists', () => {
    connectRealtime()
    mockGetAccessToken.mockReturnValue('test-token')
    mockWs.onclose!()
    vi.advanceTimersByTime(90_000)
    expect(WebSocket).toHaveBeenCalledTimes(2)
  })

  it('does not reconnect on close when no token', () => {
    connectRealtime()
    mockGetAccessToken.mockReturnValue(null)
    mockWs.onclose!()
    vi.advanceTimersByTime(90_000)
    expect(WebSocket).toHaveBeenCalledTimes(1)
  })

  it('reset reconnect attempt on successful open', () => {
    connectRealtime()
    mockWs.onopen!()
    expect(mockWs.readyState).toBe(0)
  })
})

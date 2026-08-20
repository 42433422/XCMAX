import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyDevProxyReachablePort, buildPairingQrText, resolveReachablePairingPort, type PairingPayload } from './mobilePairing'

describe('mobilePairing', () => {
  it('builds v2 QR text with host, port, nonce, and short code', () => {
    const payload: PairingPayload = {
      host: '192.168.1.20',
      port: 5100,
      nonce: 'nonce-abc',
      shortCode: '123456',
      exp: 1_800_000_000,
    }

    expect(JSON.parse(buildPairingQrText(payload))).toEqual({
      v: 2,
      t: '123456',
      host: '192.168.1.20',
      port: 5100,
      nonce: 'nonce-abc',
    })
  })

  it('rewrites loopback API port to vite proxy for LAN phones', () => {
    const payload: PairingPayload = {
      host: '192.168.10.2',
      port: 17500,
      nonce: 'nonce-abc',
      shortCode: '123456',
      exp: 1_800_000_000,
    }
    vi.stubGlobal('window', {
      location: { hostname: '127.0.0.1', port: '5011' },
    } as Window & typeof globalThis)
    const reachable = applyDevProxyReachablePort(payload)
    expect(reachable.port).toBe(5011)
    expect(reachable.host).toBe('192.168.10.2')
    expect(JSON.parse(buildPairingQrText(reachable))).toEqual({
      v: 2,
      t: '123456',
      host: '192.168.10.2',
      port: 5011,
      nonce: 'nonce-abc',
    })
    vi.unstubAllGlobals()
  })
})

describe('resolveReachablePairingPort', () => {
  const originalWindow = globalThis.window

  afterEach(() => {
    if (originalWindow === undefined) {
      // @ts-expect-error restore SSR-like state
      delete (globalThis as Record<string, unknown>).window
    } else {
      globalThis.window = originalWindow
    }
    vi.restoreAllMocks()
  })

  function setWindowLocation(port: number | string) {
    const portNum = Number(port)
    Object.defineProperty(globalThis, 'window', {
      value: {
        location: {
          port: portNum > 0 ? String(portNum) : '',
          hostname: '192.168.10.2',
        },
      },
      configurable: true,
      writable: true,
    })
  }

  it('prefers page port (vite proxy 5011) over backend hint (17500) when they differ', () => {
    setWindowLocation(5011)
    expect(resolveReachablePairingPort(17500)).toBe(5011)
  })

  it('returns hint port when page port equals hint port (direct backend access)', () => {
    setWindowLocation(5100)
    expect(resolveReachablePairingPort(5100)).toBe(5100)
  })

  it('returns hint port when page is on standard 80 (production, no explicit port)', () => {
    setWindowLocation(0) // window.location.port is '' on port 80
    expect(resolveReachablePairingPort(5100)).toBe(5100)
  })

  it('falls back to hint port when window is unavailable (SSR)', () => {
    // @ts-expect-error simulate SSR without window
    delete (globalThis as Record<string, unknown>).window
    expect(resolveReachablePairingPort(17500)).toBe(17500)
  })

  it('falls back to default when both page port and hint port are unavailable', () => {
    // @ts-expect-error simulate SSR without window
    delete (globalThis as Record<string, unknown>).window
    expect(resolveReachablePairingPort(0)).toBe(5000)
  })
})

import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '@/utils/apiBase'
import { applyDevProxyReachablePort, buildPairingQrText, fetchHostDiscoverHint, issueMobilePairing, loadDesktopPairingPayload, resolvePairingHost, resolvePairingPortHint, resolveReachablePairingPort, type PairingPayload } from './mobilePairing'

vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn() }))

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


describe('pairing transport and retained desktop QR payload', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.restoreAllMocks(); vi.mocked(apiFetch).mockReset() })

  it('unwraps discovery metadata and posts exactly the requested host and port', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify({ data: { api_port: 5100 } })))
    expect(await fetchHostDiscoverHint()).toEqual({ api_port: 5100 })
    const payload = { host: '192.168.1.8', port: 5100, nonce: 'owned', shortCode: '123456', exp: 300 }
    vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify(payload)))
    expect(await issueMobilePairing(payload.host, payload.port)).toEqual(payload)
    expect(apiFetch).toHaveBeenNthCalledWith(1, '/api/mobile/v1/host/discover-hint')
    expect(apiFetch).toHaveBeenNthCalledWith(2, '/api/mobile/v1/pairing/issue', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ host: payload.host, port: payload.port }),
    })
  })

  it.each([
    [401, { message: '请重新授权' }, '', '请重新授权'],
    [200, { success: false }, 'Denied', 'Denied'],
    [200, { success: false }, '', '请求失败'],
  ])('never treats a denied pairing response as a payload (%s)', async (status, data, statusText, message) => {
    vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify(data), { status, statusText }))
    await expect(issueMobilePairing('127.0.0.1', 5000)).rejects.toThrow(message)
  })

  it.each([undefined, {}, { getPairingQrPayload: async () => null }, { getPairingQrPayload: async () => '{}' }])('does not fabricate a desktop binding without a nonce or retained QR', async desktop => {
    vi.stubGlobal('window', { xcagiDesktop: desktop })
    expect(await loadDesktopPairingPayload()).toBeNull()
  })

  it('retains a legacy nonce with deterministic defaults, not a fabricated short code', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_000_000)
    vi.stubGlobal('window', { xcagiDesktop: { getPairingQrPayload: async () => '{"nonce":"server-nonce"}' } })
    expect(await loadDesktopPairingPayload()).toEqual({ host: '127.0.0.1', port: 5000, nonce: 'server-nonce', shortCode: '', exp: 1300 })
  })

  it('preserves v3 relay authority and emits the retained QR instead of reconstructing it', async () => {
    const qr = { v: 3, relay_id: 'owned-relay', t: '654321' }
    const raw = { host: '192.168.1.3', port: 5100, shortCode: '654321', exp: 1800, relay_id: 'owned-relay', relay_base_url: 'https://relay.example.invalid', qr_json: qr, relay: { id: 'owned-relay' } }
    vi.stubGlobal('window', { xcagiDesktop: { getPairingQrPayload: async () => JSON.stringify(raw) } })
    const payload = await loadDesktopPairingPayload()
    expect(payload).toEqual({ ...raw, nonce: '' })
    expect(JSON.parse(buildPairingQrText(payload!))).toEqual(qr)
  })

  it('rejects corrupt desktop JSON rather than making a pairing payload', async () => {
    vi.stubGlobal('window', { xcagiDesktop: { getPairingQrPayload: async () => '{bad' } })
    await expect(loadDesktopPairingPayload()).rejects.toThrow(SyntaxError)
  })

  it('uses a LAN page host and only an explicit supported API hint', () => {
    vi.stubGlobal('window', { location: { hostname: ' 192.168.8.2 ', port: '5100' } })
    expect(resolvePairingHost()).toBe('192.168.8.2')
    expect(resolvePairingPortHint(7000)).toBe(5100)
    vi.stubGlobal('window', undefined); vi.stubEnv('VITE_FHD_PORT', '7200')
    expect(resolvePairingHost()).toBe('127.0.0.1')
    expect(resolvePairingPortHint(7000)).toBe(7200)
  })
})

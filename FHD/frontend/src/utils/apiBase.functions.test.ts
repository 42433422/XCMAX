import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { mockReadActiveExtensionModId, mockReadCsrfToken, mockShouldAttachCsrf } = vi.hoisted(() => ({
  mockReadActiveExtensionModId: vi.fn(() => ''),
  mockReadCsrfToken: vi.fn(() => null),
  mockShouldAttachCsrf: vi.fn(() => false),
}))

vi.mock('./xcagiStorageKeys', () => ({
  readActiveExtensionModIdFromStorage: mockReadActiveExtensionModId,
}))

vi.mock('./csrfCookie', () => ({
  readCsrfTokenFromCookie: mockReadCsrfToken,
  shouldAttachCsrfHeader: mockShouldAttachCsrf,
}))

import {
  DEFAULT_MOD_API_TIMEOUT_MS,
  MOD_PROBE_API_TIMEOUT_MS,
  isApiFetchTimeoutError,
  getApiBase,
  apiUrl,
  getClientModsUiOffHeader,
  getActiveExtensionModHeaders,
  apiFetch,
  pushClientModsOffState,
  syncClientModsStateToBackend,
  readClientModsOffState,
} from './apiBase'

describe('apiBase constants', () => {
  it('DEFAULT_MOD_API_TIMEOUT_MS is 90000', () => {
    expect(DEFAULT_MOD_API_TIMEOUT_MS).toBe(90_000)
  })

  it('MOD_PROBE_API_TIMEOUT_MS is 8000', () => {
    expect(MOD_PROBE_API_TIMEOUT_MS).toBe(8_000)
  })
})

describe('isApiFetchTimeoutError', () => {
  it('returns true for DOMException AbortError with apiFetch timeout message', () => {
    const e = new DOMException('apiFetch timeout after 5000ms', 'AbortError')
    expect(isApiFetchTimeoutError(e)).toBe(true)
  })

  it('returns true for Error with name AbortError and apiFetch timeout message', () => {
    const e = new Error('apiFetch timeout after 5000ms')
    e.name = 'AbortError'
    expect(isApiFetchTimeoutError(e)).toBe(true)
  })

  it('returns false for AbortError without apiFetch timeout message', () => {
    const e = new DOMException('user aborted', 'AbortError')
    expect(isApiFetchTimeoutError(e)).toBe(false)
  })

  it('returns false for generic Error', () => {
    expect(isApiFetchTimeoutError(new Error('network failed'))).toBe(false)
  })

  it('returns false for non-Error value', () => {
    expect(isApiFetchTimeoutError('string')).toBe(false)
    expect(isApiFetchTimeoutError(null)).toBe(false)
    expect(isApiFetchTimeoutError(undefined)).toBe(false)
    expect(isApiFetchTimeoutError(42)).toBe(false)
  })
})

describe('getApiBase', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    delete (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__
  })

  it('returns empty string when no injected base and no env', () => {
    vi.stubEnv('VITE_API_BASE', '')
    vi.stubEnv('VITE_API_BASE_URL', '')
    expect(getApiBase()).toBe('')
  })

  it('returns injected base when set', () => {
    ;(window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = '/fhd-api'
    expect(getApiBase()).toBe('/fhd-api')
  })

  it('trims trailing slash from injected base', () => {
    ;(window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = '/fhd-api/'
    expect(getApiBase()).toBe('/fhd-api')
  })

  it('returns empty string for injected localhost base', () => {
    ;(window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = 'http://localhost:5000'
    expect(getApiBase()).toBe('')
  })

  it('returns empty string for injected 127.0.0.1 base', () => {
    ;(window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = 'http://127.0.0.1:5000'
    expect(getApiBase()).toBe('')
  })

  it('returns empty string for injected localhost without port', () => {
    ;(window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = 'http://localhost'
    expect(getApiBase()).toBe('')
  })

  it('returns empty string for localhost env base (loopback exception)', () => {
    vi.stubEnv('VITE_API_BASE', 'http://localhost:5000')
    vi.stubEnv('VITE_API_BASE_URL', '')
    expect(getApiBase()).toBe('')
  })

  it('returns empty string for 127.0.0.1 env base (loopback exception)', () => {
    vi.stubEnv('VITE_API_BASE', 'http://127.0.0.1:5000')
    vi.stubEnv('VITE_API_BASE_URL', '')
    expect(getApiBase()).toBe('')
  })

  it('returns empty string for cross-origin env base in DEV mode (prefer relative)', () => {
    vi.stubEnv('VITE_API_BASE', 'https://api.example.com')
    vi.stubEnv('VITE_API_BASE_URL', '')
    // In DEV mode, shouldPreferRelativeApiBase() returns true and cross-origin returns ''
    expect(getApiBase()).toBe('')
  })
})

describe('apiUrl', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    delete (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__
  })

  it('returns path as-is when no base', () => {
    vi.stubEnv('VITE_API_BASE', '')
    vi.stubEnv('VITE_API_BASE_URL', '')
    expect(apiUrl('/api/users')).toBe('/api/users')
  })

  it('prepends base when set', () => {
    ;(window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = '/fhd-api'
    expect(apiUrl('/api/users')).toBe('/fhd-api/api/users')
  })

  it('adds leading slash to path when missing', () => {
    ;(window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = '/fhd-api'
    expect(apiUrl('api/users')).toBe('/fhd-api/api/users')
  })

  it('handles path without leading slash and no base', () => {
    vi.stubEnv('VITE_API_BASE', '')
    vi.stubEnv('VITE_API_BASE_URL', '')
    expect(apiUrl('api/users')).toBe('/api/users')
  })
})

describe('getClientModsUiOffHeader', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns empty object when key not set', () => {
    expect(getClientModsUiOffHeader()).toEqual({})
  })

  it('returns X-Client-Mods-Off header when key is "1"', () => {
    localStorage.setItem('xcagi_client_mods_ui_off', '1')
    expect(getClientModsUiOffHeader()).toEqual({ 'X-Client-Mods-Off': '1' })
  })

  it('returns empty object when key is "0"', () => {
    localStorage.setItem('xcagi_client_mods_ui_off', '0')
    expect(getClientModsUiOffHeader()).toEqual({})
  })

  it('returns empty object when key is any other value', () => {
    localStorage.setItem('xcagi_client_mods_ui_off', 'yes')
    expect(getClientModsUiOffHeader()).toEqual({})
  })
})

describe('getActiveExtensionModHeaders', () => {
  beforeEach(() => {
    mockReadActiveExtensionModId.mockReset()
  })

  it('returns empty object when no active mod id in storage', () => {
    mockReadActiveExtensionModId.mockReturnValue('')
    expect(getActiveExtensionModHeaders('/api/users')).toEqual({})
  })

  it('returns header with mod id when set', () => {
    mockReadActiveExtensionModId.mockReturnValue('taiyangniao-pro')
    expect(getActiveExtensionModHeaders('/api/users')).toEqual({
      'X-XCAGI-Active-Mod-Id': 'taiyangniao-pro',
    })
  })

  it('skips header for /api/auth/ paths', () => {
    mockReadActiveExtensionModId.mockReturnValue('taiyangniao-pro')
    expect(getActiveExtensionModHeaders('/api/auth/login')).toEqual({})
  })

  it('skips header for /api/platform-shell/ paths', () => {
    mockReadActiveExtensionModId.mockReturnValue('taiyangniao-pro')
    expect(getActiveExtensionModHeaders('/api/platform-shell/menu')).toEqual({})
  })

  it('skips header for /api/debug/ paths', () => {
    mockReadActiveExtensionModId.mockReturnValue('taiyangniao-pro')
    expect(getActiveExtensionModHeaders('/api/debug/info')).toEqual({})
  })

  it('returns header for full URL with non-skip path', () => {
    mockReadActiveExtensionModId.mockReturnValue('taiyangniao-pro')
    expect(getActiveExtensionModHeaders('https://example.com/api/users')).toEqual({
      'X-XCAGI-Active-Mod-Id': 'taiyangniao-pro',
    })
  })

  it('skips header for full URL with /api/auth/ path', () => {
    mockReadActiveExtensionModId.mockReturnValue('taiyangniao-pro')
    expect(getActiveExtensionModHeaders('https://example.com/api/auth/login')).toEqual({})
  })

  it('returns header when url is empty (default behavior)', () => {
    mockReadActiveExtensionModId.mockReturnValue('taiyangniao-pro')
    expect(getActiveExtensionModHeaders()).toEqual({
      'X-XCAGI-Active-Mod-Id': 'taiyangniao-pro',
    })
  })

  it('returns header when url is whitespace', () => {
    mockReadActiveExtensionModId.mockReturnValue('taiyangniao-pro')
    expect(getActiveExtensionModHeaders('   ')).toEqual({
      'X-XCAGI-Active-Mod-Id': 'taiyangniao-pro',
    })
  })

  it('returns empty object when readActiveExtensionModIdFromStorage throws', () => {
    mockReadActiveExtensionModId.mockImplementation(() => {
      throw new Error('storage error')
    })
    expect(getActiveExtensionModHeaders('/api/users')).toEqual({})
  })
})

describe('apiFetch', () => {
  beforeEach(() => {
    mockReadActiveExtensionModId.mockReset()
    mockReadCsrfToken.mockReset()
    mockShouldAttachCsrf.mockReset()
    mockReadActiveExtensionModId.mockReturnValue('')
    mockReadCsrfToken.mockReturnValue(null)
    mockShouldAttachCsrf.mockReturnValue(false)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  it('calls fetch with the resolved URL', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok'))
    await apiFetch('/api/test')
    expect(fetchSpy).toHaveBeenCalled()
    const calledUrl = fetchSpy.mock.calls[0][0]
    expect(String(calledUrl)).toContain('/api/test')
  })

  it('passes through headers from init', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok'))
    await apiFetch('/api/test', {
      headers: { 'X-Custom': 'value' },
    })
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers['X-Custom']).toBe('value')
  })

  it('includes credentials: include', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok'))
    await apiFetch('/api/test')
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    expect(init.credentials).toBe('include')
  })

  it('attaches active mod header when present', async () => {
    mockReadActiveExtensionModId.mockReturnValue('my-mod')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok'))
    await apiFetch('/api/users')
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers['X-XCAGI-Active-Mod-Id']).toBe('my-mod')
  })

  it('attaches CSRF token when shouldAttachCsrfHeader returns true', async () => {
    mockShouldAttachCsrf.mockReturnValue(true)
    mockReadCsrfToken.mockReturnValue('csrf-token-123')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok'))
    await apiFetch('/api/test', { method: 'POST' })
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers['X-CSRF-Token']).toBe('csrf-token-123')
  })

  it('does not attach CSRF token when shouldAttachCsrfHeader returns false', async () => {
    mockShouldAttachCsrf.mockReturnValue(false)
    mockReadCsrfToken.mockReturnValue('csrf-token-123')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok'))
    await apiFetch('/api/test', { method: 'GET' })
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers['X-CSRF-Token']).toBeUndefined()
  })

  it('passes through method from init', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok'))
    await apiFetch('/api/test', { method: 'POST' })
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
  })

  it('defaults method to GET when not specified (not stored in fetchInit)', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok'))
    await apiFetch('/api/test')
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    // method is not stored back into fetchInit when not specified; fetch defaults to GET
    expect(init.method).toBeUndefined()
  })

  it('uses absolute URL when input starts with http', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok'))
    await apiFetch('https://example.com/api/test')
    expect(fetchSpy.mock.calls[0][0]).toBe('https://example.com/api/test')
  })
})

describe('pushClientModsOffState', () => {
  beforeEach(() => {
    mockReadActiveExtensionModId.mockReset()
    mockReadCsrfToken.mockReset()
    mockShouldAttachCsrf.mockReset()
    mockReadActiveExtensionModId.mockReturnValue('')
    mockReadCsrfToken.mockReturnValue(null)
    mockShouldAttachCsrf.mockReturnValue(false)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('throws when response is not ok', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('fail', { status: 500 }))
    await expect(pushClientModsOffState(true)).rejects.toThrow(/同步原版模式失败/)
  })

  it('resolves when response is ok', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok', { status: 200 }))
    await expect(pushClientModsOffState(true)).resolves.toBeUndefined()
  })

  it('sends POST with client_mods_off in body', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok', { status: 200 }))
    await pushClientModsOffState(false)
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify({ client_mods_off: false }))
  })
})

describe('syncClientModsStateToBackend', () => {
  beforeEach(() => {
    localStorage.clear()
    mockReadActiveExtensionModId.mockReset()
    mockReadCsrfToken.mockReset()
    mockShouldAttachCsrf.mockReset()
    mockReadActiveExtensionModId.mockReturnValue('')
    mockReadCsrfToken.mockReturnValue(null)
    mockShouldAttachCsrf.mockReturnValue(false)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('resolves when fetch succeeds with ok response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok', { status: 200 }))
    await expect(syncClientModsStateToBackend()).resolves.toBeUndefined()
  })

  it('resolves even when response is not ok (does not throw)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('fail', { status: 500 }))
    await expect(syncClientModsStateToBackend()).resolves.toBeUndefined()
  })

  it('resolves when fetch throws timeout error (silently)', async () => {
    const timeoutErr = new DOMException('apiFetch timeout after 25000ms', 'AbortError')
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(timeoutErr)
    await expect(syncClientModsStateToBackend()).resolves.toBeUndefined()
  })

  it('resolves when fetch throws generic error (silently)', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network failed'))
    await expect(syncClientModsStateToBackend()).resolves.toBeUndefined()
  })

  it('sends current state from localStorage', async () => {
    localStorage.setItem('xcagi_client_mods_ui_off', '1')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('ok', { status: 200 }))
    await syncClientModsStateToBackend()
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    expect(init.body).toBe(JSON.stringify({ client_mods_off: true }))
  })
})

describe('readClientModsOffState', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns false when key not set', () => {
    expect(readClientModsOffState()).toBe(false)
  })

  it('returns true when key is "1"', () => {
    localStorage.setItem('xcagi_client_mods_ui_off', '1')
    expect(readClientModsOffState()).toBe(true)
  })

  it('returns false when key is "0"', () => {
    localStorage.setItem('xcagi_client_mods_ui_off', '0')
    expect(readClientModsOffState()).toBe(false)
  })

  it('returns false when key is any other value', () => {
    localStorage.setItem('xcagi_client_mods_ui_off', 'yes')
    expect(readClientModsOffState()).toBe(false)
  })
})

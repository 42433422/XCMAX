import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

describe('installFetchDbReadToken', () => {
  let originalFetch: typeof window.fetch

  beforeEach(() => {
    originalFetch = window.fetch
    delete (window as any).__XCAGI_FHD_FETCH_PATCHED
    vi.resetModules()
    vi.doMock('@/utils/apiBase', () => ({
      getApiBase: vi.fn().mockReturnValue(''),
      getActiveExtensionModHeaders: vi.fn().mockReturnValue({}),
      getClientModsUiOffHeader: vi.fn().mockReturnValue({}),
    }))
  })

  afterEach(() => {
    window.fetch = originalFetch
    delete (window as any).__XCAGI_FHD_FETCH_PATCHED
  })

  it('patches window.fetch on first call', async () => {

    const { installFetchDbReadToken } = await import('@/fhd/installFetchDbReadToken')
    window.fetch = originalFetch
    delete (window as any).__XCAGI_FHD_FETCH_PATCHED
    installFetchDbReadToken()
    expect((window as any).__XCAGI_FHD_FETCH_PATCHED).toBe(true)
  })

  it('does not patch twice', async () => {

    const { installFetchDbReadToken } = await import('@/fhd/installFetchDbReadToken')
    window.fetch = originalFetch
    delete (window as any).__XCAGI_FHD_FETCH_PATCHED
    installFetchDbReadToken()
    const firstPatched = window.fetch
    installFetchDbReadToken()
    expect(window.fetch).toBe(firstPatched)
  })

  it('calls native fetch for requests', async () => {

    const mockFetch = vi.fn().mockResolvedValue(new Response())
    window.fetch = mockFetch
    delete (window as any).__XCAGI_FHD_FETCH_PATCHED

    const { installFetchDbReadToken } = await import('@/fhd/installFetchDbReadToken')
    installFetchDbReadToken()

    await window.fetch('/api/test')
    expect(mockFetch).toHaveBeenCalled()
  })

  it('attaches Mod headers only to same-origin or configured API requests', async () => {
    vi.doMock('@/utils/apiBase', () => ({
      getApiBase: () => 'https://api.example.test',
      getActiveExtensionModHeaders: () => ({ 'X-XCAGI-Active-Mod-Id': 'mod-a' }),
      getClientModsUiOffHeader: () => ({ 'X-Client-Mods-Ui-Off': '1' }),
    }))
    const native = vi.fn().mockResolvedValue(new Response())
    window.fetch = native
    await import('@/fhd/installFetchDbReadToken')

    await window.fetch('/api/products', { headers: { 'X-Existing': 'yes' } })
    const localHeaders = native.mock.calls[0][1].headers as Headers
    expect(localHeaders.get('X-Existing')).toBe('yes')
    expect(localHeaders.get('X-XCAGI-Active-Mod-Id')).toBe('mod-a')
    await window.fetch(new URL('https://api.example.test/api/products'))
    expect((native.mock.calls[1][1].headers as Headers).get('X-Client-Mods-Ui-Off')).toBe('1')
    await window.fetch('https://untrusted.example/api/products')
    expect(native.mock.calls[2][1]).toBeUndefined()
  })
})

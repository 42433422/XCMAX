import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

describe('installFetchDbReadToken', () => {
  let originalFetch: typeof window.fetch

  beforeEach(() => {
    originalFetch = window.fetch
    delete (window as any).__XCAGI_FHD_FETCH_PATCHED
    vi.resetModules()
  })

  afterEach(() => {
    window.fetch = originalFetch
    delete (window as any).__XCAGI_FHD_FETCH_PATCHED
  })

  it('patches window.fetch on first call', async () => {
    vi.doMock('@/components/fhd/dbTokenHeaders', () => ({
      dbReadHeaders: vi.fn().mockReturnValue({}),
      dbWriteHeaders: vi.fn().mockReturnValue({}),
      shouldAttachDbReadToken: vi.fn().mockReturnValue(false),
      urlNeedsDbWriteToken: vi.fn().mockReturnValue(false),
    }))
    vi.doMock('@/utils/apiBase', () => ({
      getApiBase: vi.fn().mockReturnValue(''),
      getActiveExtensionModHeaders: vi.fn().mockReturnValue({}),
      getClientModsUiOffHeader: vi.fn().mockReturnValue({}),
    }))

    const { installFetchDbReadToken } = await import('@/fhd/installFetchDbReadToken')
    window.fetch = originalFetch
    delete (window as any).__XCAGI_FHD_FETCH_PATCHED
    installFetchDbReadToken()
    expect((window as any).__XCAGI_FHD_FETCH_PATCHED).toBe(true)
  })

  it('does not patch twice', async () => {
    vi.doMock('@/components/fhd/dbTokenHeaders', () => ({
      dbReadHeaders: vi.fn().mockReturnValue({}),
      dbWriteHeaders: vi.fn().mockReturnValue({}),
      shouldAttachDbReadToken: vi.fn().mockReturnValue(false),
      urlNeedsDbWriteToken: vi.fn().mockReturnValue(false),
    }))
    vi.doMock('@/utils/apiBase', () => ({
      getApiBase: vi.fn().mockReturnValue(''),
      getActiveExtensionModHeaders: vi.fn().mockReturnValue({}),
      getClientModsUiOffHeader: vi.fn().mockReturnValue({}),
    }))

    const { installFetchDbReadToken } = await import('@/fhd/installFetchDbReadToken')
    window.fetch = originalFetch
    delete (window as any).__XCAGI_FHD_FETCH_PATCHED
    installFetchDbReadToken()
    const firstPatched = window.fetch
    installFetchDbReadToken()
    expect(window.fetch).toBe(firstPatched)
  })

  it('calls native fetch for requests', async () => {
    vi.doMock('@/components/fhd/dbTokenHeaders', () => ({
      dbReadHeaders: vi.fn().mockReturnValue({}),
      dbWriteHeaders: vi.fn().mockReturnValue({}),
      shouldAttachDbReadToken: vi.fn().mockReturnValue(false),
      urlNeedsDbWriteToken: vi.fn().mockReturnValue(false),
    }))
    vi.doMock('@/utils/apiBase', () => ({
      getApiBase: vi.fn().mockReturnValue(''),
      getActiveExtensionModHeaders: vi.fn().mockReturnValue({}),
      getClientModsUiOffHeader: vi.fn().mockReturnValue({}),
    }))

    const mockFetch = vi.fn().mockResolvedValue(new Response())
    window.fetch = mockFetch
    delete (window as any).__XCAGI_FHD_FETCH_PATCHED

    const { installFetchDbReadToken } = await import('@/fhd/installFetchDbReadToken')
    installFetchDbReadToken()

    await window.fetch('/api/test')
    expect(mockFetch).toHaveBeenCalled()
  })
})

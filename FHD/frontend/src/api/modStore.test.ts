import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  getModCatalog,
  fetchMarketCatalog,
  searchMods,
  getPopularMods,
  getRecentMods,
  getModDetails,
} from './modStore'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
}))

import { apiFetch } from '@/utils/apiBase'

function mockJson(body: unknown, ok = true) {
  return {
    ok,
    json: async () => body,
  } as Response
}

describe('modStore api', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset()
  })

  it('getModCatalog returns data on success', async () => {
    const catalog = { installed: [], available: [], indexed_count: 0 }
    vi.mocked(apiFetch).mockResolvedValue(mockJson({ success: true, data: catalog }))
    await expect(getModCatalog()).resolves.toEqual(catalog)
  })

  it('getModCatalog throws on failure', async () => {
    vi.mocked(apiFetch).mockResolvedValue(mockJson({ success: false, error: 'boom' }))
    await expect(getModCatalog()).rejects.toThrow('boom')
  })

  it('fetchMarketCatalog builds query params', async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      mockJson({ success: true, data: { items: [], total: 0, collection: 'all' } }),
    )
    await fetchMarketCatalog({ q: 'test', limit: 10 })
    const url = vi.mocked(apiFetch).mock.calls[0][0] as string
    expect(url).toContain('q=test')
    expect(url).toContain('limit=10')
  })

  it('searchMods forwards filters', async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      mockJson({ success: true, data: { data: [], count: 0 } }),
    )
    await searchMods('abc', 'author', true, 5)
    const url = vi.mocked(apiFetch).mock.calls[0][0] as string
    expect(url).toContain('q=abc')
    expect(url).toContain('author=author')
    expect(url).toContain('installed=true')
  })

  it('getPopularMods and getRecentMods', async () => {
    vi.mocked(apiFetch).mockResolvedValue(mockJson({ success: true, data: [{ id: 'm1' }] }))
    await expect(getPopularMods(3)).resolves.toEqual([{ id: 'm1' }])
    await expect(getRecentMods(2)).resolves.toEqual([{ id: 'm1' }])
  })

  it('getModDetails fetches by id', async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      mockJson({ success: true, data: { id: 'x', name: 'X' } }),
    )
    const d = await getModDetails('x')
    expect(d.id).toBe('x')
    expect(apiFetch).toHaveBeenCalledWith('/api/mod-store/mod/x/details')
  })
})

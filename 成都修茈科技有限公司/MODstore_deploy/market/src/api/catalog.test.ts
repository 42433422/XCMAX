import { describe, expect, it, vi, beforeEach } from 'vitest'
import { catalog } from './catalog'
import { req, authHeaders, fetchZipBlob } from './shared'

vi.mock('./shared', () => ({
  req: vi.fn(),
  authHeaders: vi.fn(() => ({ Authorization: 'Bearer test' })),
  fetchZipBlob: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('catalog api', () => {
  it('catalog uses default params', async () => {
    vi.mocked(req).mockResolvedValue({ items: [] })
    await catalog.catalog()
    expect(req).toHaveBeenCalledWith(expect.stringContaining('/api/market/catalog?'))
    const call = vi.mocked(req).mock.calls[0] as any[]
    const url = call[0] as string
    expect(url).toContain('limit=50')
    expect(url).toContain('offset=0')
  })

  it('catalog passes q and artifact params', async () => {
    vi.mocked(req).mockResolvedValue({ items: [] })
    await catalog.catalog('search', 'employee_pack')
    const call = vi.mocked(req).mock.calls[0] as any[]
    const url = call[0] as string
    expect(url).toContain('q=search')
    expect(url).toContain('artifact=employee_pack')
  })

  it('catalog passes industry and securityLevel', async () => {
    vi.mocked(req).mockResolvedValue({ items: [] })
    await catalog.catalog('', '', 50, 0, 'tech', 'high')
    const call = vi.mocked(req).mock.calls[0] as any[]
    const url = call[0] as string
    expect(url).toContain('industry=tech')
    expect(url).toContain('security_level=high')
  })

  it('catalog adds cacheBust param', async () => {
    vi.mocked(req).mockResolvedValue({ items: [] })
    await catalog.catalog('', '', 50, 0, '', '', '', '', true)
    const call = vi.mocked(req).mock.calls[0] as any[]
    const url = call[0] as string
    expect(url).toContain('_cb=')
  })

  it('catalogFacets calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await catalog.catalogFacets()
    expect(req).toHaveBeenCalledWith('/api/market/facets')
  })

  it('catalogDetail encodes id', async () => {
    vi.mocked(req).mockResolvedValue({})
    await catalog.catalogDetail('pkg/1')
    expect(req).toHaveBeenCalledWith('/api/market/catalog/pkg%2F1')
  })

  it('catalogReviews calls req', async () => {
    vi.mocked(req).mockResolvedValue([])
    await catalog.catalogReviews(42)
    expect(req).toHaveBeenCalledWith('/api/market/catalog/42/reviews')
  })

  it('catalogQuality calls quality endpoint', async () => {
    vi.mocked(req).mockResolvedValue({ ok: true })
    await catalog.catalogQuality(42)
    expect(req).toHaveBeenCalledWith('/api/market/catalog/42/quality')
    await catalog.catalogQuality(42, { refresh: true })
    expect(req).toHaveBeenCalledWith('/api/market/catalog/42/quality?refresh=1')
    await catalog.catalogQuality(42, { llm: true })
    expect(req).toHaveBeenCalledWith('/api/market/catalog/42/quality?llm=1')
  })

  it('catalogSubmitReview calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await catalog.catalogSubmitReview(1, 5, 'great')
    expect(req).toHaveBeenCalledWith('/api/market/catalog/1/review', expect.objectContaining({ method: 'POST' }))
  })

  it('catalogSubmitComplaint calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await catalog.catalogSubmitComplaint(1, 'spam', 'bad content')
    expect(req).toHaveBeenCalledWith('/api/market/catalog/1/complaints', expect.objectContaining({ method: 'POST' }))
  })

  it('catalogToggleFavorite calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await catalog.catalogToggleFavorite(1)
    expect(req).toHaveBeenCalledWith('/api/market/catalog/1/favorite', expect.objectContaining({ method: 'POST' }))
  })

  it('buyItem calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await catalog.buyItem(1)
    expect(req).toHaveBeenCalledWith('/api/market/catalog/1/buy', expect.objectContaining({ method: 'POST' }))
  })

  it('downloadItem fetches zip and triggers download', async () => {
    const blob = new Blob([], { type: 'application/zip' })
    vi.mocked(fetchZipBlob).mockResolvedValue(blob)
    const createObjectURL = vi.fn(() => 'blob:test')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
    const clickSpy = vi.fn()
    const removeSpy = vi.fn()
    const origCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreateElement(tag)
      if (tag === 'a') {
        el.click = clickSpy
        el.remove = removeSpy
      }
      return el
    })
    const appendSpy = vi.spyOn(document.body, 'appendChild').mockImplementation((node) => node)

    await catalog.downloadItem(1)

    expect(fetchZipBlob).toHaveBeenCalled()
    expect(createObjectURL).toHaveBeenCalled()
    expect(clickSpy).toHaveBeenCalled()
    expect(removeSpy).toHaveBeenCalled()

    appendSpy.mockRestore()
    vi.unstubAllGlobals()
  })

  it('myStore uses default params', async () => {
    vi.mocked(req).mockResolvedValue({})
    await catalog.myStore()
    expect(req).toHaveBeenCalledWith('/api/my-store?limit=50&offset=0')
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { searchApi } from './search'

vi.mock('./core', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ success: true, results: {} }),
  },
}))

describe('searchApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('searchV0 calls GET /api/search/v0 with default scope and perPage', async () => {
    await searchApi.searchV0('test query')
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/search/v0', {
      q: 'test query',
      scope: 'all',
      per_page: 20,
    })
  })

  it('searchV0 passes custom scope and perPage', async () => {
    await searchApi.searchV0('products', 'products', 10)
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/search/v0', {
      q: 'products',
      scope: 'products',
      per_page: 10,
    })
  })

  it('searchV0 uses excel scope', async () => {
    await searchApi.searchV0('data', 'excel')
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/search/v0', {
      q: 'data',
      scope: 'excel',
      per_page: 20,
    })
  })

  it('searchV0 uses customers scope', async () => {
    await searchApi.searchV0('acme', 'customers', 5)
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/search/v0', {
      q: 'acme',
      scope: 'customers',
      per_page: 5,
    })
  })
})

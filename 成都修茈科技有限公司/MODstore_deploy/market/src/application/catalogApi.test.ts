import { describe, expect, it, vi, beforeEach } from 'vitest'
import * as catalogApi from './catalogApi'
import { requestJson } from '../infrastructure/http/client'

vi.mock('../infrastructure/http/client', () => ({
  requestJson: vi.fn(),
}))

describe('catalogApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('listCatalog calls requestJson with default params', async () => {
    vi.mocked(requestJson).mockResolvedValue({ items: [] })
    await catalogApi.listCatalog()
    expect(requestJson).toHaveBeenCalledWith('/api/market/catalog?limit=50&offset=0')
  })

  it('listCatalog passes custom limit and offset', async () => {
    vi.mocked(requestJson).mockResolvedValue({ items: [] })
    await catalogApi.listCatalog(10, 5)
    expect(requestJson).toHaveBeenCalledWith('/api/market/catalog?limit=10&offset=5')
  })

  it('getCatalogDetail calls requestJson with item id', async () => {
    vi.mocked(requestJson).mockResolvedValue({ id: 42 })
    await catalogApi.getCatalogDetail(42)
    expect(requestJson).toHaveBeenCalledWith('/api/market/catalog/42')
  })
})

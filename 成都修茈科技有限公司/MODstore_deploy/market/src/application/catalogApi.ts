import { requestJson } from '../infrastructure/http/client'
import type { CatalogDetail, CatalogListResponse } from '../domain/catalog/types'

export function listCatalog(limit = 50, offset = 0): Promise<CatalogListResponse> {
  return requestJson(`/api/market/catalog?limit=${limit}&offset=${offset}`)
}

export function getCatalogDetail(itemId: number): Promise<CatalogDetail> {
  return requestJson(`/api/market/catalog/${itemId}`)
}

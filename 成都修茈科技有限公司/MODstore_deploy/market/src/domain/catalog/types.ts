/**
 * 与 modstore_server/market_api.py `api_market_catalog` / `api_market_catalog_detail` 字段对齐。
 */
export interface CatalogItem {
  id: number
  pkg_id?: string
  version?: string
  name: string
  description?: string
  price?: number
  artifact?: string
  material_category?: string
  material_category_label?: string
  license_scope?: string
  license_scope_label?: string
  origin_type?: string
  ip_risk_level?: string
  compliance_status?: string
  rank_score?: number
  delist_reason?: string
  complaint_count?: number
  industry?: string
  security_level?: string
  author_id?: number | null
  purchased?: boolean
  /** ISO 字符串；后端无创建时间则为空串 */
  created_at?: string
}

export interface CatalogDetail extends CatalogItem {
  favorited?: boolean
  user_has_review?: boolean
}

export interface CatalogListResponse {
  items: CatalogItem[]
  total: number
}

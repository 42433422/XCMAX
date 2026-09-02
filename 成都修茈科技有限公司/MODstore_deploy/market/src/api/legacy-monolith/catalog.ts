// 市场目录域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { fetchZipBlob } from '../../infrastructure/http/client'
import { authHeaders, req } from './shared'

export const catalogEndpoints = {
  catalog: (
    q = '',
    artifact = '',
    limit = 50,
    offset = 0,
    industry = '',
    securityLevel = '',
    materialCategory = '',
    licenseScope = '',
    cacheBust = false,
  ) => {
    const p = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (q) p.set('q', q)
    if (artifact) p.set('artifact', artifact)
    if (industry) p.set('industry', industry)
    if (securityLevel) p.set('security_level', securityLevel)
    if (materialCategory) p.set('material_category', materialCategory)
    if (licenseScope) p.set('license_scope', licenseScope)
    if (cacheBust) p.set('_cb', String(Date.now()))
    return req(`/api/market/catalog?${p}`)
  },
  catalogFacets: () => req('/api/market/facets'),
  catalogDetail: (id: string | number) => req(`/api/market/catalog/${encodeURIComponent(String(id))}`),
  catalogQuality: (id: string | number, opts: boolean | { refresh?: boolean; llm?: boolean } = false) => {
    const options = typeof opts === 'boolean' ? { refresh: opts } : opts
    const params = new URLSearchParams()
    if (options.refresh) params.set('refresh', '1')
    if (options.llm) params.set('llm', '1')
    const q = params.toString()
    return req(`/api/market/catalog/${encodeURIComponent(String(id))}/quality${q ? `?${q}` : ''}`)
  },
  catalogReviews: (id: string | number) => req(`/api/market/catalog/${encodeURIComponent(String(id))}/reviews`),
  catalogSubmitReview: (id: string | number, rating: number, content = '') =>
    req(`/api/market/catalog/${encodeURIComponent(String(id))}/review`, { method: 'POST', body: JSON.stringify({ rating, content }) }),
  catalogSubmitComplaint: (id: string | number, complaintType: string, reason: string, evidence: Record<string, unknown> = {}) =>
    req(`/api/market/catalog/${encodeURIComponent(String(id))}/complaints`, {
      method: 'POST',
      body: JSON.stringify({ complaint_type: complaintType, reason, evidence }),
    }),
  catalogToggleFavorite: (id: string | number) => req(`/api/market/catalog/${encodeURIComponent(String(id))}/favorite`, { method: 'POST', body: '{}' }),
  buyItem: (id: string | number) => req(`/api/market/catalog/${encodeURIComponent(String(id))}/buy`, { method: 'POST' }),
  downloadItem: async (id: string | number) => {
    const blob = await fetchZipBlob(`/api/market/catalog/${encodeURIComponent(String(id))}/download`, authHeaders())
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `mod-${id}.zip`
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    a.remove()
    // 延后释放，避免浏览器尚未读完流时立即 revoke 导致落盘 0 字节
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  },
  myStore: (limit = 50, offset = 0) => req(`/api/my-store?limit=${limit}&offset=${offset}`),
}

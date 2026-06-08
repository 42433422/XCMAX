import { req, authHeaders, fetchZipBlob } from './shared'

export const catalog = {
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
    collection = '',
  ) => {
    const p = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (q) p.set('q', q)
    if (artifact) p.set('artifact', artifact)
    if (industry) p.set('industry', industry)
    if (securityLevel) p.set('security_level', securityLevel)
    if (materialCategory) p.set('material_category', materialCategory)
    if (licenseScope) p.set('license_scope', licenseScope)
    if (collection) p.set('collection', collection)
    if (cacheBust) p.set('_cb', String(Date.now()))
    return req(`/api/market/catalog?${p}`)
  },
  downloadOfficeEmployeePack: async () => {
    const blob = await fetchZipBlob('/api/market/catalog/office-employee-pack/bundle', authHeaders())
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'office-employee-pack.zip'
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  },
  downloadWorkflowEmployeePack: async () => {
    const blob = await fetchZipBlob('/api/market/catalog/workflow-employee-pack/bundle', authHeaders())
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'workflow-employee-pack.zip'
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  },
  downloadHostFoundationEmployeePack: async () => {
    const blob = await fetchZipBlob(
      '/api/market/catalog/host-foundation-employee-pack/download',
      authHeaders(),
    )
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'xcagi-host-foundation-employee.xcemp'
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
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
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  },
  myStore: (limit = 50, offset = 0) => req(`/api/my-store?limit=${limit}&offset=${offset}`),
}

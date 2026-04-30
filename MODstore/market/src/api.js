const BASE = ''

function getToken() {
  return localStorage.getItem('modstore_token') || ''
}

async function req(path, opts = {}) {
  const method = (opts.method || 'GET').toUpperCase()
  const headers = { ...(opts.headers || {}) }
  const token = getToken()
  if (token && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${token}`
  }
  const body = opts.body
  if (!(body instanceof FormData) && method !== 'GET' && method !== 'HEAD' && body !== undefined) {
    if (!headers['Content-Type'] && !headers['content-type']) {
      headers['Content-Type'] = 'application/json'
    }
  }
  const r = await fetch(`${BASE}${path}`, { ...opts, method, headers, body })
  const text = await r.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = { detail: text || r.statusText } }
  if (!r.ok) {
    const d = data?.detail
    let msg
    if (Array.isArray(d)) msg = d.map(x => x.msg || JSON.stringify(x)).join('; ')
    else if (typeof d === 'string') msg = d
    else if (d && typeof d === 'object') msg = JSON.stringify(d)
    else msg = r.statusText
    throw new Error(msg)
  }
  return data
}

export const api = {
  register: (username, password, email) =>
    req('/api/auth/register', { method: 'POST', body: JSON.stringify({ username, password, email }) }),
  login: (username, password) =>
    req('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  me: () => req('/api/auth/me'),

  balance: () => req('/api/wallet/balance'),
  recharge: (amount, description) =>
    req('/api/wallet/recharge', { method: 'POST', body: JSON.stringify({ amount, description }) }),
  transactions: (limit = 50, offset = 0) =>
    req(`/api/wallet/transactions?limit=${limit}&offset=${offset}`),

  catalog: (q = '', artifact = '', limit = 50, offset = 0) => {
    let url = `/api/market/catalog?limit=${limit}&offset=${offset}`
    if (q) url += `&q=${encodeURIComponent(q)}`
    if (artifact) url += `&artifact=${encodeURIComponent(artifact)}`
    return req(url)
  },
  catalogDetail: (id) => req(`/api/market/catalog/${id}`),
  buyItem: (id) => req(`/api/market/catalog/${id}/buy`, { method: 'POST' }),
  downloadItem: (id) => {
    const token = getToken()
    return fetch(`${BASE}/api/market/catalog/${id}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).then(async (r) => {
      if (!r.ok) {
        const text = await r.text()
        throw new Error(text || r.statusText)
      }
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `mod-${id}.zip`
      a.click()
      URL.revokeObjectURL(url)
    })
  },

  myStore: (limit = 50, offset = 0) =>
    req(`/api/my-store?limit=${limit}&offset=${offset}`),
}

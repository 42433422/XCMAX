/** 生产可设 VITE_API_BASE（勿尾斜杠），例如同源反代或独立 API 域 */
function apiBase(): string {
  const raw = (import.meta.env?.VITE_API_BASE ?? '').toString().trim()
  if (raw) return raw.replace(/\/$/, '')
  return '' // 使用相对路径，通过 Vite 代理转发
}

const BASE = apiBase()

export interface CheckoutData {
  item_id?: number | string
  plan_id?: string
  subject?: string
  total_amount?: number | string
  wallet_recharge?: boolean
  [key: string]: unknown
}

interface CheckoutSignPayload extends Record<string, string> {
  item_id: string
  plan_id: string
  request_id: string
  subject: string
  timestamp: string
  total_amount: string
  wallet_recharge: 'true' | 'false'
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: BodyInit | null
}

function getToken(): string {
  return localStorage.getItem('modstore_token') || ''
}

function amountSignStr(n: number | string | null | undefined): string {
  const x = Number(n)
  if (!Number.isFinite(x)) return '0'
  if (x === Math.trunc(x)) return String(Math.trunc(x))
  const s = x.toFixed(6).replace(/\.?0+$/, '')
  return s || '0'
}

export function buildCheckoutSignData(
  data: CheckoutData,
  requestId: string,
  timestamp: number | string,
): CheckoutSignPayload {
  const itemId = Number(data.item_id ?? 0) | 0
  const planId = String(data.plan_id ?? '').trim()
  const subject = String(data.subject ?? '').trim()
  const walletRecharge = Boolean(data.wallet_recharge)
  return {
    item_id: String(itemId),
    plan_id: planId,
    request_id: String(requestId),
    subject,
    timestamp: String(Math.floor(Number(timestamp))),
    total_amount: amountSignStr(data.total_amount ?? 0),
    wallet_recharge: walletRecharge ? 'true' : 'false',
  }
}

function paymentSecretKey(): string {
  const fromEnv = (import.meta.env?.VITE_PAYMENT_SECRET ?? '').toString().trim()
  return fromEnv || 'default_secret_key'
}

function generateRequestId(): string {
  return 'req_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9)
}

export async function generateSignature(
  data: Record<string, string>,
  secret: string,
): Promise<string> {
  const sortedKeys = Object.keys(data).sort()
  const signString = sortedKeys.map((k) => `${k}=${data[k]}`).join('&') + secret
  const encoder = new TextEncoder()
  const dataBuffer = encoder.encode(signString)
  const buffer = await crypto.subtle.digest('SHA-256', dataBuffer)
  const hexArray = Array.from(new Uint8Array(buffer))
  return hexArray.map((b) => b.toString(16).padStart(2, '0')).join('')
}

async function req<T = any>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = (opts.method || 'GET').toUpperCase()
  const headers: Record<string, string> = { ...((opts.headers as Record<string, string>) || {}) }
  const token = getToken()
  if (token && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${token}`
  }
  const body = opts.body
  if (
    !(body instanceof FormData) &&
    method !== 'GET' &&
    method !== 'HEAD' &&
    body !== undefined &&
    body !== null
  ) {
    if (!headers['Content-Type'] && !headers['content-type']) {
      headers['Content-Type'] = 'application/json'
    }
  }
  const r = await fetch(`${BASE}${path}`, { ...opts, method, headers, body })
  const text = await r.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { detail: text || r.statusText }
  }
  if (!r.ok) {
    const d = (data as { detail?: unknown } | null)?.detail
    let msg: string
    if (Array.isArray(d)) {
      msg = d
        .map((x: unknown) => {
          if (typeof x === 'object' && x !== null && 'msg' in x) {
            return String((x as { msg?: unknown }).msg ?? JSON.stringify(x))
          }
          return JSON.stringify(x)
        })
        .join('; ')
    } else if (typeof d === 'string') {
      msg = d
    } else if (d && typeof d === 'object') {
      msg = JSON.stringify(d)
    } else {
      msg = r.statusText
    }
    throw new Error(msg)
  }
  return data as T
}

export const api = {
  register: (username: string, password: string, email: string, verificationCode = '') =>
    req('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        username,
        password,
        email,
        verification_code: verificationCode,
      }),
    }),
  login: (username: string, password: string) =>
    req('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  me: () => req('/api/auth/me'),

  sendVerificationCode: (email: string) =>
    req('/api/auth/send-code', { method: 'POST', body: JSON.stringify({ email }) }),
  sendRegisterVerificationCode: (email: string) =>
    req('/api/auth/send-register-code', { method: 'POST', body: JSON.stringify({ email }) }),
  loginWithCode: (email: string, code: string) =>
    req('/api/auth/login-with-code', { method: 'POST', body: JSON.stringify({ email, code }) }),

  balance: () => req('/api/wallet/balance'),
  recharge: (amount: number | string, description?: string) =>
    req('/api/wallet/recharge', {
      method: 'POST',
      body: JSON.stringify({ amount, description }),
    }),
  transactions: (limit = 50, offset = 0) =>
    req(`/api/wallet/transactions?limit=${limit}&offset=${offset}`),

  catalog: (q = '', artifact = '', limit = 50, offset = 0, industry = '', securityLevel = '') => {
    let url = `/api/market/catalog?limit=${limit}&offset=${offset}`
    if (q) url += `&q=${encodeURIComponent(q)}`
    if (artifact) url += `&artifact=${encodeURIComponent(artifact)}`
    if (industry) url += `&industry=${encodeURIComponent(industry)}`
    if (securityLevel) url += `&security_level=${encodeURIComponent(securityLevel)}`
    return req(url)
  },
  catalogFacets: () => req('/api/market/facets'),
  catalogDetail: (id: number | string) => req(`/api/market/catalog/${id}`),
  buyItem: (id: number | string) => req(`/api/market/catalog/${id}/buy`, { method: 'POST' }),
  downloadItem: (id: number | string) => {
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

  myStore: (limit = 50, offset = 0) => req(`/api/my-store?limit=${limit}&offset=${offset}`),

  adminStatus: () => req('/api/admin/status'),
  adminUpload: (formData: FormData) => req('/api/admin/catalog', { method: 'POST', body: formData }),
  adminListCatalog: (limit = 200, offset = 0) =>
    req(`/api/admin/catalog?limit=${limit}&offset=${offset}`),
  adminDeleteCatalog: (id: number | string) =>
    req(`/api/admin/catalog/${id}`, { method: 'DELETE' }),
  adminListUsers: (limit = 200, offset = 0) =>
    req(`/api/admin/users?limit=${limit}&offset=${offset}`),
  adminSetUserAdmin: (userId: number | string, isAdmin: boolean) =>
    req(`/api/admin/users/${userId}/admin?is_admin=${isAdmin}`, { method: 'PUT' }),
  adminListWallets: (limit = 200, offset = 0) =>
    req(`/api/admin/wallets?limit=${limit}&offset=${offset}`),
  adminListTransactions: (limit = 200, offset = 0) =>
    req(`/api/admin/transactions?limit=${limit}&offset=${offset}`),

  paymentPlans: () => req('/api/payment/plans'),
  paymentCheckout: async (data: CheckoutData) => {
    const requestId = generateRequestId()
    const timestamp = Math.floor(Date.now() / 1000)
    const signPayload = buildCheckoutSignData(data, requestId, timestamp)
    const signature = await generateSignature(signPayload, paymentSecretKey())
    return req('/api/payment/checkout', {
      method: 'POST',
      body: JSON.stringify({
        ...data,
        request_id: requestId,
        timestamp,
        signature,
      }),
    })
  },
  paymentQuery: (orderId: string | number) => req(`/api/payment/query/${orderId}`),
  paymentOrders: (status = '', limit = 50, offset = 0) => {
    let url = `/api/payment/orders?limit=${limit}&offset=${offset}`
    if (status) url += `&status=${encodeURIComponent(status)}`
    return req(url)
  },
  paymentDiagnostics: () => req('/api/payment/diagnostics'),
  paymentEntitlements: () => req('/api/payment/entitlements'),

  // Repository APIs
  listMods: () => req('/api/mods'),
  createMod: (mod_id: string, display_name: string) =>
    req('/api/mods/create', {
      method: 'POST',
      body: JSON.stringify({ mod_id, display_name }),
    }),
  importZIP: async (file: File, replace = true) => {
    const fd = new FormData()
    fd.append('file', file)
    const r = await fetch(`${BASE}/api/mods/import?replace=${replace}`, {
      method: 'POST',
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
      body: fd,
    })
    const data = await r.json().catch(() => ({}) as Record<string, unknown>)
    if (!r.ok) {
      const detail = (data as { detail?: string }).detail
      throw new Error(detail || r.statusText)
    }
    return data
  },
  modAiScaffold: (brief: string, suggestedId = '', replace = true) =>
    req('/api/mods/ai-scaffold', {
      method: 'POST',
      body: JSON.stringify({
        brief,
        suggested_id: suggestedId || undefined,
        replace,
      }),
    }),
  push: (mod_ids: string[] | null | undefined) =>
    req('/api/sync/push', {
      method: 'POST',
      body: JSON.stringify({ mod_ids: mod_ids || null }),
    }),
  pull: (mod_ids: string[] | null | undefined) =>
    req('/api/sync/pull', {
      method: 'POST',
      body: JSON.stringify({ mod_ids: mod_ids || null }),
    }),

  getMod: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}`),
  putModManifest: (modId: string, manifest: unknown) =>
    req(`/api/mods/${encodeURIComponent(modId)}/manifest`, {
      method: 'PUT',
      body: JSON.stringify({ manifest }),
    }),
  getModFile: (modId: string, path: string) =>
    req(`/api/mods/${encodeURIComponent(modId)}/file?path=${encodeURIComponent(path)}`),
  putModFile: (modId: string, path: string, content: string) =>
    req(`/api/mods/${encodeURIComponent(modId)}/file`, {
      method: 'PUT',
      body: JSON.stringify({ path, content }),
    }),
  getModAuthoringSummary: (modId: string) =>
    req(`/api/mods/${encodeURIComponent(modId)}/authoring-summary`),
  getModBlueprintRoutes: (modId: string) =>
    req(`/api/mods/${encodeURIComponent(modId)}/blueprint-routes`),
  getAuthoringExtensionSurface: (mergeHost = false) =>
    req(`/api/authoring/extension-surface?merge_host=${mergeHost ? 'true' : 'false'}`),
}

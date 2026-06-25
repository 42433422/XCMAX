/** 生产可设 VITE_API_BASE（勿尾斜杠），例如同源反代或独立 API 域 */
function apiBase(): string {
  const raw = (import.meta.env?.VITE_API_BASE ?? '').toString().trim()
  if (raw) return raw.replace(/\/$/, '')
  return '' // 使用相对路径，通过 Vite 代理转发
}

const BASE = apiBase()

export const ACCESS_TOKEN_KEY = 'modstore_token'
export const REFRESH_TOKEN_KEY = 'modstore_refresh_token'

export interface CheckoutData {
  item_id?: number | string
  plan_id?: string
  subject?: string
  total_amount?: number | string
  wallet_recharge?: boolean
  pay_channel?: string
  pay_type?: string
  [key: string]: unknown
}

/** 服务端 ``/api/payment/sign-checkout`` 返回，已含 request_id/timestamp/signature。 */
interface PaymentSignResponse {
  plan_id: string
  item_id: number
  total_amount: number
  subject: string
  wallet_recharge: boolean
  request_id: string
  timestamp: number
  signature: string
}

export interface AuthResponse {
  access_token?: string
  refresh_token?: string
  /** 旧后端兼容字段 */
  token?: string
  ok?: boolean
  user?: { id: number; username?: string; email?: string; is_admin?: boolean }
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: BodyInit | null
}

// ---- token 存储（access + refresh）-----------------------------------------

export function getToken(): string {
  const raw = localStorage.getItem(ACCESS_TOKEN_KEY)
  return raw && raw !== 'undefined' && raw !== 'null' ? raw : ''
}

function getRefreshToken(): string {
  const raw = localStorage.getItem(REFRESH_TOKEN_KEY)
  return raw && raw !== 'undefined' && raw !== 'null' ? raw : ''
}

/** 写入登录/刷新返回的双令牌；兼容旧后端 ``token`` 字段。 */
export function setAuthTokens(res: AuthResponse | null | undefined): void {
  const access = res?.access_token || res?.token
  if (access) localStorage.setItem(ACCESS_TOKEN_KEY, access)
  if (res?.refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, res.refresh_token)
}

export function clearAuthTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}

// ---- CSRF（双提交 Cookie，与后端 CSRFMiddleware 对齐）----------------------

function readCsrfTokenFromCookie(): string | null {
  if (typeof document === 'undefined') return null
  for (const part of document.cookie.split(';')) {
    const s = part.trim()
    if (s.startsWith('csrf_token=')) {
      const v = s.slice('csrf_token='.length)
      try {
        return decodeURIComponent(v)
      } catch {
        return v
      }
    }
  }
  return null
}

/**
 * 写操作（非 GET/HEAD/OPTIONS）若无 Bearer，则附带与 Cookie 一致的 X-CSRF-Token。
 * 后端对带 Bearer 的请求豁免 CSRF（无 Cookie 凭据，不存在 CSRF 面），故此处与之一致。
 */
function attachCsrfHeader(headers: Record<string, string>, method: string): void {
  const m = method.toUpperCase()
  if (m === 'GET' || m === 'HEAD' || m === 'OPTIONS') return
  if (headers['Authorization'] || headers['authorization']) return
  if (headers['X-CSRF-Token']) return
  const tok = readCsrfTokenFromCookie()
  if (tok) headers['X-CSRF-Token'] = tok
}

// ---- access token 刷新（401 时一次性重试）---------------------------------

let refreshInFlight: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return null
  const r = await fetch(`${BASE}/api/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  let data: AuthResponse | null = null
  try {
    const text = await r.text()
    data = text ? (JSON.parse(text) as AuthResponse) : null
  } catch {
    data = null
  }
  if (!r.ok) {
    clearAuthTokens()
    return null
  }
  setAuthTokens(data)
  return data?.access_token || data?.token || null
}

function refreshAccessTokenOnce(): Promise<string | null> {
  if (!refreshInFlight) {
    refreshInFlight = refreshAccessToken().finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

function shouldSkipRefresh(path: string): boolean {
  return (
    path.includes('/api/auth/login') ||
    path.includes('/api/auth/register') ||
    path.includes('/api/auth/login-with-code') ||
    path.includes('/api/auth/refresh') ||
    path.includes('/api/auth/send-')
  )
}

function looksLikeAuthFailure(path: string, status: number): boolean {
  const pathOnly = path.split('?')[0] || path
  return (
    status === 401 ||
    (status === 403 &&
      (path.includes('/api/payment') ||
        path.includes('/api/wallet') ||
        path.includes('/api/refunds') ||
        path.includes('/api/admin') ||
        pathOnly === '/api/auth/me'))
  )
}

function errorMessage(data: unknown, fallback: string): string {
  const d = (data as { detail?: unknown } | null)?.detail
  if (Array.isArray(d)) {
    return d
      .map((x: unknown) => {
        if (typeof x === 'object' && x !== null && 'msg' in x) {
          return String((x as { msg?: unknown }).msg ?? JSON.stringify(x))
        }
        return JSON.stringify(x)
      })
      .join('; ')
  }
  if (typeof d === 'string') return d
  if (d && typeof d === 'object') return JSON.stringify(d)
  return fallback
}

// 默认返回类型保持 ``any``（与重构前一致；严格化属 P0-7 范畴，不在本次安全修复范围）。
async function req<T = any>(path: string, opts: RequestOptions = {}, authAttempt = 0): Promise<T> {
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
  attachCsrfHeader(headers, method)
  const r = await fetch(`${BASE}${path}`, { ...opts, method, headers, body, credentials: 'include' })
  const text = await r.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { detail: text || r.statusText }
  }
  // access token 过期：用 refresh token 静默刷新一次后重试原请求。
  if (
    looksLikeAuthFailure(path, r.status) &&
    authAttempt === 0 &&
    getToken() &&
    !shouldSkipRefresh(path)
  ) {
    const newToken = await refreshAccessTokenOnce()
    if (newToken) return req<T>(path, opts, 1)
  }
  if (!r.ok) {
    throw new Error(errorMessage(data, r.statusText))
  }
  return data as T
}

export const api = {
  register: (username: string, password: string, email: string, verificationCode = '') =>
    req<AuthResponse>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        username,
        password,
        email,
        verification_code: verificationCode,
      }),
    }),
  login: (username: string, password: string) =>
    req<AuthResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  me: () => req('/api/auth/me'),

  sendVerificationCode: (email: string) =>
    req('/api/auth/send-code', { method: 'POST', body: JSON.stringify({ email }) }),
  sendRegisterVerificationCode: (email: string) =>
    req('/api/auth/send-register-code', { method: 'POST', body: JSON.stringify({ email }) }),
  loginWithCode: (email: string, code: string) =>
    req<AuthResponse>('/api/auth/login-with-code', {
      method: 'POST',
      body: JSON.stringify({ email, code }),
    }),

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
      credentials: 'include',
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
  /**
   * 下单：签名完全在服务端完成（``/api/payment/sign-checkout`` 用仅存于后端环境
   * 的 PAYMENT_SECRET_KEY 计算 HMAC），前端不接触任何密钥，仅传业务参数。
   */
  paymentCheckout: async (data: CheckoutData) => {
    const sign = await req<PaymentSignResponse>('/api/payment/sign-checkout', {
      method: 'POST',
      body: JSON.stringify({
        plan_id: data.plan_id ?? '',
        item_id: Number(data.item_id ?? 0) || 0,
        total_amount: Number(data.total_amount ?? 0) || 0,
        subject: data.subject ?? '',
        wallet_recharge: Boolean(data.wallet_recharge),
      }),
    })
    const checkoutBody: Record<string, unknown> = {
      plan_id: sign.plan_id ?? '',
      item_id: sign.item_id ?? 0,
      total_amount: sign.total_amount ?? 0,
      subject: sign.subject ?? '',
      wallet_recharge: Boolean(sign.wallet_recharge),
      request_id: sign.request_id,
      timestamp: sign.timestamp,
      signature: sign.signature,
    }
    if (data.pay_channel) checkoutBody.pay_channel = data.pay_channel
    if (data.pay_type) checkoutBody.pay_type = data.pay_type
    return req('/api/payment/checkout', {
      method: 'POST',
      body: JSON.stringify(checkoutBody),
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
    const headers: Record<string, string> = {}
    if (getToken()) headers['Authorization'] = `Bearer ${getToken()}`
    attachCsrfHeader(headers, 'POST')
    const r = await fetch(`${BASE}/api/mods/import?replace=${replace}`, {
      method: 'POST',
      credentials: 'include',
      headers,
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

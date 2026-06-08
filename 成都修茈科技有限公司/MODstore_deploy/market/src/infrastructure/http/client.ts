import { clearAuthTokens, getAccessToken, getRefreshToken, setAuthTokens } from '../storage/tokenStore'

/**
 * 接口基址与 Vite 静态 base（/market/）分离。
 * 线上 nginx 通常把 `/api/` 反代到 modstore（见 market/nginx.conf），勿默认拼成 `/market/api`。
 * 若部署把 API 挂在子路径，在构建时设置 VITE_API_BASE=/market。
 */
const BASE = String(import.meta.env.VITE_API_BASE || '')
  .trim()
  .replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function parseResponse(res: Response): Promise<unknown> {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return { detail: text || res.statusText }
  }
}

function looksLikeHtmlErrorBody(s: string): boolean {
  const t = s.trim()
  return t.startsWith('<!') || /^<html/i.test(t)
}

function errorMessage(data: any, fallback: string): string {
  const m = data?.message
  if (typeof m === 'string' && m.trim()) return m.trim()
  const d = data?.detail
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join('; ')
  if (typeof d === 'string') {
    if (looksLikeHtmlErrorBody(d)) {
      if (/504|Gateway Time-out/i.test(d)) {
        return 'HTTP 504 Gateway Time-out（网关读超时：长请求请在 nginx 增大 proxy_read_timeout，见 MODstore_deploy/docs/nginx-https-example.conf）'
      }
      if (/502|Bad Gateway/i.test(d)) {
        return 'HTTP 502 Bad Gateway（上游不可用或连接被重置）'
      }
      return fallback || '网关返回了 HTML 错误页而非 JSON'
    }
    return d
  }
  if (d && typeof d === 'object') return JSON.stringify(d)
  return fallback
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return null
  const res = await fetch(`${BASE}/api/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  const data: any = await parseResponse(res)
  if (!res.ok) {
    clearAuthTokens()
    return null
  }
  setAuthTokens(data)
  return data?.access_token || null
}

let refreshInFlight: Promise<string | null> | null = null

function readCsrfTokenFromCookie(): string | null {
  if (typeof document === 'undefined') return null
  for (const part of document.cookie.split(';')) {
    const s = part.trim()
    if (s.startsWith('csrf_token=')) {
      try {
        return decodeURIComponent(s.slice('csrf_token='.length))
      } catch {
        return s.slice('csrf_token='.length)
      }
    }
  }
  return null
}

/** 与后端 CSRFMiddleware 对齐：无 Bearer 的变更请求需带与 Cookie 一致的 X-CSRF-Token。 */
function attachCsrfHeader(headers: Headers, method: string): void {
  const m = method.toUpperCase()
  if (m === 'GET' || m === 'HEAD' || m === 'OPTIONS') return
  if (headers.has('Authorization')) return
  if (headers.has('X-CSRF-Token')) return
  const tok = readCsrfTokenFromCookie()
  if (tok) headers.set('X-CSRF-Token', tok)
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

function prepareAuthedRequest(path: string, opts: RequestInit = {}) {
  const method = (opts.method || 'GET').toUpperCase()
  const headers = new Headers(opts.headers || {})
  const token = getAccessToken()
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
  const body = opts.body
  if (!(body instanceof FormData) && method !== 'GET' && method !== 'HEAD' && body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  attachCsrfHeader(headers, method)
  return { method, headers, body }
}

function looksLikeAuthFailure(path: string, res: Response): boolean {
  const pathOnly = path.split('?')[0] || path
  return (
    res.status === 401 ||
    (res.status === 403 &&
      (path.includes('/api/payment') ||
        path.includes('/api/wallet') ||
        path.includes('/api/refunds') ||
        path.includes('/api/admin') ||
        pathOnly === '/api/auth/me'))
  )
}

async function throwIfNotOk(res: Response): Promise<void> {
  if (res.ok) return
  let detail: unknown
  try {
    detail = await res.json()
  } catch {
    try {
      detail = await res.text()
    } catch {
      detail = null
    }
  }
  throw new ApiError(errorMessage(detail as any, res.statusText), res.status, detail)
}

export type RequestJsonInit = RequestInit & {
  /** 超时后中止 fetch（常用于员工 execute-file / LLM 长任务）。 */
  timeoutMs?: number
}

export async function requestJson<T extends unknown = any>(
  path: string,
  opts: RequestJsonInit = {},
  authAttempt = 0,
): Promise<T> {
  const { timeoutMs, ...fetchOpts } = opts
  const { method, headers, body } = prepareAuthedRequest(path, fetchOpts)

  const timeoutController = timeoutMs && timeoutMs > 0 ? new AbortController() : null
  const timeoutId =
    timeoutController != null
      ? setTimeout(() => {
          timeoutController.abort()
        }, timeoutMs)
      : null
  const mergedSignal = timeoutController
    ? fetchOpts.signal
      ? AbortSignal.any([fetchOpts.signal, timeoutController.signal])
      : timeoutController.signal
    : fetchOpts.signal

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...fetchOpts,
      method,
      headers,
      body,
      credentials: 'include',
      signal: mergedSignal,
    })
  } catch (e: unknown) {
    if (timeoutController?.signal.aborted && (e as Error)?.name === 'AbortError') {
      throw new ApiError(
        '请求超时（LLM 生成量化报告可能需 1–3 分钟；若反复超时请检查 API Key 或稍后重试）。',
        408,
        null,
      )
    }
    throw e
  } finally {
    if (timeoutId != null) clearTimeout(timeoutId)
  }
  const data = await parseResponse(res)
  const pathOnly = path.split('?')[0] || path
  const looksLikeAuthFailure =
    res.status === 401 ||
    (res.status === 403 &&
      (path.includes('/api/payment') ||
        path.includes('/api/wallet') ||
        path.includes('/api/refunds') ||
        path.includes('/api/admin') ||
        path.includes('/api/auth/verify-admin-digest-code') ||
        pathOnly === '/api/auth/me'))
  if (
    looksLikeAuthFailure &&
    authAttempt === 0 &&
    getAccessToken() &&
    !shouldSkipRefresh(path) &&
    !headers.has('X-Skip-Auth-Refresh')
  ) {
    const newToken = await refreshAccessTokenOnce()
    if (newToken) return requestJson<T>(path, opts, 1)
  }
  if (!res.ok) {
    let msg = errorMessage(data, res.statusText)
    if (res.status === 504) {
      msg =
        'HTTP 504 Gateway Time-out（网关在等待上游响应时超时。工作台 LLM / 基准测试可能需数分钟：请为 location /api/ 设置 proxy_read_timeout 3600s 或更高。）'
    } else if (res.status === 503) {
      msg =
        'HTTP 503 Service Unavailable（上游过载或未就绪。请在浏览器 Network 面板确认具体 URL：常见于 /api/llm/status、/api/llm/catalog 或网关到后端的连接。）'
    } else if (typeof msg === 'string' && msg.length > 600) {
      msg = `${msg.slice(0, 400)}…`
    }
    throw new ApiError(msg, res.status, data)
  }
  return data as T
}

export async function fetchZipBlob(path: string, headers?: HeadersInit): Promise<Blob> {
  const res = await fetch(`${BASE}${path}`, headers ? { headers } : {})
  const buf = await res.arrayBuffer()
  if (!res.ok) {
    throw new ApiError(res.statusText || '请求失败', res.status)
  }
  const u8 = new Uint8Array(buf)
  if (buf.byteLength < 4 || u8[0] !== 0x50 || u8[1] !== 0x4b) {
    throw new Error('响应不是 zip 文件')
  }
  return new Blob([buf], { type: 'application/zip' })
}

/** 与 requestJson 相同的鉴权与 401 刷新逻辑，返回二进制（如 TTS 音频）。 */
export async function requestBlob(path: string, opts: RequestInit = {}, authAttempt = 0): Promise<Blob> {
  const { method, headers, body } = prepareAuthedRequest(path, opts)

  const res = await fetch(`${BASE}${path}`, { ...opts, method, headers, body, credentials: 'include' })
  if (
    looksLikeAuthFailure(path, res) &&
    authAttempt === 0 &&
    getAccessToken() &&
    !shouldSkipRefresh(path) &&
    !headers.has('X-Skip-Auth-Refresh')
  ) {
    const newToken = await refreshAccessTokenOnce()
    if (newToken) return requestBlob(path, opts, 1)
  }
  await throwIfNotOk(res)
  return res.blob()
}

/** 鉴权 fetch，返回原始 Response（供 TTS MSE 边下边播）。 */
export async function requestStreamResponse(path: string, opts: RequestInit = {}, authAttempt = 0): Promise<Response> {
  const { method, headers, body } = prepareAuthedRequest(path, opts)

  const res = await fetch(`${BASE}${path}`, { ...opts, method, headers, body, credentials: 'include' })
  if (
    looksLikeAuthFailure(path, res) &&
    authAttempt === 0 &&
    getAccessToken() &&
    !shouldSkipRefresh(path) &&
    !headers.has('X-Skip-Auth-Refresh')
  ) {
    const newToken = await refreshAccessTokenOnce()
    if (newToken) return requestStreamResponse(path, opts, 1)
  }
  await throwIfNotOk(res)
  return res
}

/** 与 requestBlob 相同鉴权，但以 ReadableStream 逐块读取后合并为 Blob（TTS 预取缓存）。 */
export async function requestStreamBlob(path: string, opts: RequestInit = {}, authAttempt = 0): Promise<Blob> {
  const res = await requestStreamResponse(path, opts, authAttempt)
  const reader = res.body?.getReader()
  if (!reader) return res.blob()

  const chunks: BlobPart[] = []
  const contentType = res.headers.get('content-type') || 'audio/mpeg'
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (value?.byteLength) chunks.push(value)
    }
  } finally {
    reader.releaseLock()
  }
  return new Blob(chunks, { type: contentType })
}

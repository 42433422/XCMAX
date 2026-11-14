import { getApiBase } from '@/utils/apiBase'
import { readCsrfTokenFromCookie, shouldAttachCsrfHeader } from '@/utils/csrfCookie'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { clientShellRequestHeaders } from '@/utils/clientShell'
import { resolveErpApiPathWhenReady } from '@/utils/erpDomainPaths'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { classifyTransportFailure, createTraceId, noteTransportFailure, noteTransportSuccess, publishStabilityNotice, RefreshSingleFlight, SideEffectGate } from '@/utils/networkStability'

/**
 * 后端 LanLicenseGuard 返回 401 + error=license_* 时派发；
 * App.vue 侧监听并弹出 GlobalLanGateModal（避免每个业务页各自处理未授权跳转）。
 */
export const XCAGI_PROMPT_LAN_GATE_EVENT = 'xcagi:prompt-lan-gate'

const LAN_GATE_ERROR_CODES = new Set(['license_required', 'license_invalid', 'license_expired', 'license_revoked', 'license_misconfigured'])

function maybeNotifyLanGate(status: number, errorData: unknown): void {
  if (isAdminConsoleSpa()) return
  if (status !== 401 && status !== 503) return
  if (typeof window === 'undefined') return
  const payload = errorData && typeof errorData === 'object' ? (errorData as Record<string, unknown>) : {}
  const code = String(payload.error || '').trim()
  if (!LAN_GATE_ERROR_CODES.has(code)) return
  window.dispatchEvent(
    new CustomEvent(XCAGI_PROMPT_LAN_GATE_EVENT, {
      detail: {
        status,
        code,
        message: typeof payload.message === 'string' ? payload.message : '',
      },
    }),
  )
}

function buildApiUrl(url: string): string {
  const normalizedUrl = String(url || '')
  if (/^https?:\/\//i.test(normalizedUrl)) {
    return normalizedUrl
  }
  const base = getApiBase()
  if (!base) {
    return normalizedUrl
  }
  return normalizedUrl.startsWith('/') ? `${base}${normalizedUrl}` : `${base}/${normalizedUrl}`
}

/** 当前解析到的 API 基址（含 ``window.__XCMAX_API_BASE__``），随页面注入变化。 */
export function getRuntimeApiBase(): string {
  return getApiBase()
}

/** 与 api.post/get 同源；用于 fetch 健康检查等，避免已配置 API 基址时仍请求到错误源。 */
export function buildFullApiUrl(url: string): string {
  return buildApiUrl(url)
}

/**
 * 冷启动后首个变更请求（如登录 POST）前，须先有一次安全方法请求，后端 ``CSRFMiddleware``
 * 才会下发可读 ``csrf_token`` Cookie；否则 ``X-CSRF-Token`` 无法对齐 → 403「CSRF token missing」。
 */
export async function primeCsrfCookie(options: Pick<RequestOptions, 'signal' | 'timeoutMs'> = {}): Promise<void> {
  options.signal?.throwIfAborted()
  if (typeof window === 'undefined' || readCsrfTokenFromCookie()) return
  const controller = new AbortController()
  const timeoutMs = options.timeoutMs ?? 3_000
  const abortFromCaller = () => controller.abort(options.signal?.reason)
  options.signal?.addEventListener('abort', abortFromCaller, { once: true })
  const timer = setTimeout(() => controller.abort(new ApiError(`请求超时（>${Math.ceil(timeoutMs / 1000)}s）`, 0, null)), timeoutMs)
  let rejectOnAbort!: () => void
  const aborted = new Promise<never>((_, reject) => {
    rejectOnAbort = () => reject(controller.signal.reason)
    controller.signal.addEventListener('abort', rejectOnAbort, { once: true })
  })
  try {
    await Promise.race([aborted, (async () => {
      for (let attempt = 0; attempt < 3; attempt++) {
        for (const p of ['/health', '/api/health']) {
          controller.signal.throwIfAborted()
          try {
            const response = await fetch(buildFullApiUrl(p), { method: 'GET', credentials: 'include', signal: controller.signal })
            if (response.ok && readCsrfTokenFromCookie()) return
          } catch (error) {
            if (controller.signal.aborted) throw error
          }
        }
        await new Promise((resolve) => setTimeout(resolve, 80))
        controller.signal.throwIfAborted()
        if (readCsrfTokenFromCookie()) return
      }
    })()])
  } finally {
    clearTimeout(timer)
    controller.signal.removeEventListener('abort', rejectOnAbort)
    options.signal?.removeEventListener('abort', abortFromCaller)
  }
}

const defaultHeaders: Record<string, string> = {
  'Content-Type': 'application/json',
}

export class ApiError extends Error {
  status: number
  data: unknown

  constructor(message: string, status: number, data: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

export class AccountSwitchedError extends ApiError {
  constructor() {
    super('账号已切换，已丢弃旧账号的请求结果', 0, null)
    this.name = 'AccountSwitchedError'
  }
}

// Auth endpoints drive the account switch themselves, so their responses must not be discarded.
const ACCOUNT_SWITCH_EXEMPT_PATH = /\/api\/(auth|market\/auth|session)\b/

export interface RequestOptions extends RequestInit {
  skipDefaultJsonHeader?: boolean
  responseType?: 'json' | 'blob'
  timeoutMs?: number
  /** 后台轮询类请求：失败时由调用方静默降级，不弹全局稳定性提示。 */
  quiet?: boolean
  /** 显式预算的读请求（如登录行业 8s）不再自动再等一轮。 */
  retry?: boolean
  /** 同一键的写入只执行一次。结果未知时必须显式确认后才允许再提交。 */
  idempotencyKey?: string
  sideEffect?: boolean
  confirmUnknownRetry?: boolean
  authRetried?: boolean
}

const refreshGate = new RefreshSingleFlight()
const sideEffectGate = new SideEffectGate()

export function registerSessionRefresh(fn: (() => Promise<boolean>) | null): void {
  refreshGate.setRefresher(fn)
}

export type { ApiResponse } from '@/types/api'

const READ_RETRY_DELAY_MS = 250
const READ_RETRYABLE_STATUSES = new Set([408, 429])

function stabilityKind(error: ApiError): string {
  const data = error.data
  if (!data || typeof data !== 'object') return ''
  const stability = (data as { stability?: { kind?: string } }).stability
  return stability?.kind || ''
}

const RETRYABLE_TRANSPORT_KINDS = new Set(['timeout', 'offline', 'server_down', 'backend_restart'])

function isTransientReadFailure(error: ApiError): boolean {
  if (error.status >= 500 || READ_RETRYABLE_STATUSES.has(error.status)) return true
  if (RETRYABLE_TRANSPORT_KINDS.has(stabilityKind(error))) return true
  if (error.status !== 0) return false
  const message = error.message
  // 只重试传输失败和调用方设置的超时。响应形状错误不能再读一次。
  return message.startsWith('请求超时')
    || message === '网络错误'
    || /failed to fetch|network|econn|abort/i.test(message)
}

function shouldRetryRead(error: unknown, options: RequestOptions): boolean {
  if (options.retry === false || options.signal?.aborted) return false
  // 切账号必须丢弃结果，不能当成网络失败再读一次新账号的数据。
  if (error instanceof AccountSwitchedError) return false
  const method = String(options.method || 'GET').toUpperCase()
  if (method !== 'GET' && method !== 'HEAD') return false
  return error instanceof ApiError && isTransientReadFailure(error)
}

const AUTH_REFRESH_EXEMPT = /\/api\/(auth|market\/auth)\b/

async function authRecovery(
  url: string,
  status: number,
  errorData: unknown,
  options: RequestOptions,
): Promise<'retry' | 'stop' | 'none'> {
  if (status !== 401 || options.authRetried || !refreshGate.enabled) return 'none'
  if (AUTH_REFRESH_EXEMPT.test(url)) return 'none'
  const payload = errorData && typeof errorData === 'object' ? (errorData as Record<string, unknown>) : {}
  const code = String(payload.error || '').trim()
  if (LAN_GATE_ERROR_CODES.has(code)) return 'none'
  const ok = await refreshGate.run()
  return ok ? 'retry' : 'stop'
}

async function requestWithRetry<T = unknown>(url: string, options: RequestOptions = {}): Promise<T | Response> {
  const resolvedUrl = await resolveErpApiPathWhenReady(url)
  const accountEpoch = productReadAccountEpoch.value
  try {
    return await requestOnce<T>(resolvedUrl, options, accountEpoch)
  } catch (error) {
    if (!shouldRetryRead(error, options)) throw error
    if (accountEpoch !== productReadAccountEpoch.value && !ACCOUNT_SWITCH_EXEMPT_PATH.test(resolvedUrl)) {
      throw new AccountSwitchedError()
    }
    await new Promise((resolve) => setTimeout(resolve, READ_RETRY_DELAY_MS))
    if (options.signal?.aborted) throw error
    if (accountEpoch !== productReadAccountEpoch.value && !ACCOUNT_SWITCH_EXEMPT_PATH.test(resolvedUrl)) {
      throw new AccountSwitchedError()
    }
    return requestOnce<T>(resolvedUrl, options, accountEpoch)
  }
}

async function request<T = unknown>(url: string, options: RequestOptions = {}): Promise<T | Response> {
  const method = String(options.method || 'GET').toUpperCase()
  const key = options.idempotencyKey
  const sideEffect = options.sideEffect === true || (!!key && method !== 'GET' && method !== 'HEAD')
  if (sideEffect && key) {
    return sideEffectGate.submit(
      key,
      () => requestWithRetry<T>(url, options),
      options.confirmUnknownRetry === true,
    ) as Promise<T | Response>
  }
  return requestWithRetry<T>(url, options)
}

/** Office-file ELT and docking saves keep running through an 8s budget or a dropped chat. */
export function isDurableToolRequest(url: string): boolean {
  const path = String(url || '').split('?')[0]
  return /\/api\/platform-shell\/(?:office\/confirm|chat-office-file-upload)$/.test(path)
    || /\/api\/templates\/reviewed-excel\/(?:save|intake-preview|preview|refine|analyze|archive-classify)$/.test(path)
    || /\/api\/elt\//.test(path)
}

function durableToolBudget(url: string, timeoutMs: number | undefined, callerSignal: AbortSignal | null | undefined) {
  if (!isDurableToolRequest(url)) return { timeoutMs, callerSignal }
  const kept = typeof timeoutMs === 'number' && timeoutMs > 8_000 ? timeoutMs : undefined
  return { timeoutMs: kept, callerSignal: undefined as AbortSignal | undefined }
}

async function requestOnce<T = unknown>(
  url: string,
  options: RequestOptions = {},
  accountEpoch = productReadAccountEpoch.value,
): Promise<T | Response> {
  const fullUrl = buildApiUrl(url)
  const { skipDefaultJsonHeader = false, responseType = 'json', timeoutMs: requestedTimeoutMs, quiet = false, signal: requestedCallerSignal, ...requestOptions } = options
  const budget = durableToolBudget(url, requestedTimeoutMs, requestedCallerSignal)
  const timeoutMs = budget.timeoutMs
  const callerSignal = budget.callerSignal
  const timeoutController = typeof timeoutMs === 'number' && timeoutMs > 0 ? new AbortController() : null
  let timeoutId: ReturnType<typeof setTimeout> | null = null
  let detachCallerAbort: (() => void) | null = null
  if (timeoutController && typeof timeoutMs === 'number') {
    timeoutId = setTimeout(() => timeoutController.abort(), timeoutMs)
    if (callerSignal) {
      const abortFromCaller = () => timeoutController.abort(callerSignal.reason)
      if (callerSignal.aborted) abortFromCaller()
      else {
        callerSignal.addEventListener('abort', abortFromCaller, { once: true })
        detachCallerAbort = () => callerSignal.removeEventListener('abort', abortFromCaller)
      }
    }
  }
  const config: RequestOptions = {
    credentials: 'include',
    ...requestOptions,
    signal: timeoutController?.signal ?? callerSignal,
  }
  const baseHeaders = skipDefaultJsonHeader ? {} : defaultHeaders
  config.headers = {
    ...baseHeaders,
    ...clientShellRequestHeaders(),
    ...(requestOptions.headers || {}),
  }

  const method = String(config.method || 'GET')
  const headerRecord: Record<string, string | undefined> = {}
  for (const [k, v] of Object.entries(config.headers as Record<string, unknown>)) {
    headerRecord[k] = v == null ? undefined : String(v)
  }
  if (shouldAttachCsrfHeader(method, headerRecord)) {
    const tok = readCsrfTokenFromCookie()
    if (tok) {
      ;(config.headers as Record<string, string>)['X-CSRF-Token'] = tok
    }
  }
  const traceHeaders = config.headers as Record<string, string>
  const hasTrace = Object.keys(traceHeaders).some((key) => key.toLowerCase() === 'x-request-id' && String(traceHeaders[key] || '').trim())
  if (!hasTrace) traceHeaders['X-Request-ID'] = createTraceId()

  const assertSameAccount = () => {
    if (accountEpoch !== productReadAccountEpoch.value && !ACCOUNT_SWITCH_EXEMPT_PATH.test(url)) {
      throw new AccountSwitchedError()
    }
  }

  try {
    const response = await fetch(fullUrl, config)
    assertSameAccount()
    const contentType = response.headers.get('content-type') || ''

    if (!response.ok) {
      let errorData: unknown = null
      let errorMessage = `请求失败：${response.status}`

      if (contentType.includes('application/json')) {
        try {
          errorData = await response.json()
          const errObj = errorData && typeof errorData === 'object' ? (errorData as Record<string, unknown>) : {}
          const nestedError = errObj.error && typeof errObj.error === 'object' ? (errObj.error as Record<string, unknown>) : null
          const m =
            (typeof errObj.message === 'string' && errObj.message) ||
            (typeof nestedError?.message === 'string' && nestedError.message) ||
            (typeof errObj.detail === 'string' && errObj.detail)
          errorMessage = m || errorMessage
        } catch {
          // Preserve the status-based fallback when an error body is not valid JSON.
        }
      }

      assertSameAccount()
      maybeNotifyLanGate(response.status, errorData)
      const recovery = await authRecovery(url, response.status, errorData, options)
      assertSameAccount()
      if (recovery === 'retry') {
        return requestOnce<T>(url, { ...options, authRetried: true }, accountEpoch)
      }
      // Production has no experimental refresher; its definite session 401s
      // must still retire the shell, without treating license gates as logout.
      if (response.status === 401 && !AUTH_REFRESH_EXEMPT.test(url)
        && !LAN_GATE_ERROR_CODES.has(String((errorData as { error?: unknown } | null)?.error || ''))
        && typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('xcagi:enterprise-session-invalid'))
      }
      if (recovery === 'stop') {
        const expired = classifyTransportFailure({ status: 401, errorCode: 'token_expired' })
        publishStabilityNotice(expired.message)
        throw new ApiError(expired.message, 401, { success: false, stability: expired })
      }

      throw new ApiError(errorMessage, response.status, errorData)
    }

    noteTransportSuccess()
    if (responseType === 'blob') {
      return response
    }

    if (contentType.includes('application/json')) {
      const body = (await response.json()) as T
      assertSameAccount()
      return body
    }

    return response
  } catch (error: unknown) {
    if (error instanceof ApiError) {
      throw error
    }
    const rawMessage = error instanceof Error ? error.message : '网络错误'
    if (callerSignal?.aborted) {
      throw new ApiError(rawMessage, 0, { success: false, stability: { kind: 'interrupted', message: rawMessage, action: 'check_result', success: false } })
    }
    const timedOut = Boolean(timeoutController?.signal.aborted)
    const online = typeof navigator === 'undefined' ? true : navigator.onLine
    const stability = classifyTransportFailure({
      timeout: timedOut || rawMessage.includes('请求超时'),
      online,
      message: timedOut ? '请求超时' : rawMessage,
    })
    const message = timedOut
      ? `请求超时（>${Math.ceil(Number(timeoutMs) / 1000)}s）。该请求未成功。`
      : stability.message
    // 超时保留失败回执供页面处理，默认不弹全局提示；传输故障按「持续才提示」处理。
    if (!quiet && stability.kind !== 'timeout') noteTransportFailure(message)
    throw new ApiError(message, 0, { success: false, stability })
  } finally {
    if (timeoutId) clearTimeout(timeoutId)
    detachCallerAbort?.()
  }
}

export type QueryParams = Record<string, string | number | boolean | null | undefined>

export const api = {
  get<T = unknown>(url: string, params: QueryParams | object = {}, options: RequestOptions = {}): Promise<T> {
    const searchParams = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== null && value !== undefined) {
        searchParams.append(key, String(value))
      }
    })
    const queryString = searchParams.toString()
    const fullUrl = queryString ? `${url}?${queryString}` : url
    return request(fullUrl, {
      method: 'GET',
      ...options,
    }) as Promise<T>
  },

  post<T = unknown>(url: string, data: unknown = {}, options: RequestOptions = {}): Promise<T> {
    const isFormData = typeof FormData !== 'undefined' && data instanceof FormData
    const headers = { ...(options.headers || {}) }
    return request(url, {
      method: 'POST',
      body: isFormData ? data : JSON.stringify(data),
      headers,
      skipDefaultJsonHeader: isFormData,
      ...options,
    }) as Promise<T>
  },

  put<T = unknown>(url: string, data: unknown = {}, options: RequestOptions = {}): Promise<T> {
    const isFormData = typeof FormData !== 'undefined' && data instanceof FormData
    const headers = { ...(options.headers || {}) }
    return request(url, {
      method: 'PUT',
      body: isFormData ? data : JSON.stringify(data),
      headers,
      skipDefaultJsonHeader: isFormData,
      ...options,
    }) as Promise<T>
  },

  patch<T = unknown>(url: string, data: unknown = {}, options: RequestOptions = {}): Promise<T> {
    const isFormData = typeof FormData !== 'undefined' && data instanceof FormData
    const headers = { ...(options.headers || {}) }
    return request(url, {
      method: 'PATCH',
      body: isFormData ? data : JSON.stringify(data),
      headers,
      skipDefaultJsonHeader: isFormData,
      ...options,
    }) as Promise<T>
  },

  delete<T = unknown>(url: string, data: Record<string, unknown> = {}, options: RequestOptions = {}): Promise<T> {
    const config: RequestOptions = {
      method: 'DELETE',
      ...options,
    }
    if (Object.keys(data).length > 0) {
      config.body = JSON.stringify(data)
    }
    return request(url, config) as Promise<T>
  },

  download(url: string, params: QueryParams | object = {}, options: RequestOptions = {}): Promise<Response> {
    const searchParams = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== null && value !== undefined) {
        searchParams.append(key, String(value))
      }
    })
    const queryString = searchParams.toString()
    const fullUrl = queryString ? `${url}?${queryString}` : url
    return request(fullUrl, {
      method: 'GET',
      responseType: 'blob',
      ...options,
    })
  },
}

export default api

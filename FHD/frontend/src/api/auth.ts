import { clearEnterpriseCsRecovery } from '@/utils/enterpriseCsRecovery'
import { api, primeCsrfCookie, type RequestOptions } from './core'
import { clearMarketCredentials } from './marketAccount'
import { getAuthSessionEpoch, invalidateEnterpriseSessionCache, markEnterpriseSessionValid } from '@/utils/authSessionCache'
import { clearAutoLoginPreference } from '@/utils/loginPreferences'
import type { ApiResponse } from '@/types/api'

export type AccountKind = 'personal' | 'enterprise' | 'admin'
// 账号体系：等级（仅企业有意义）/ 预算区间 / 修茈市场会员等级
export type AccountTier = 'normal' | 'pro' | 'max' | 'ultra'
export type BudgetRange = '1–5 万' | '5–10 万' | '10–50 万' | '50–100 万'
export type MarketMembershipTier = string // free | vip | vip_plus | svip1..svip8

export interface LoginRequest {
  username: string
  password: string
  account_kind?: AccountKind
  invitation_code?: string
}

export interface User {
  id: number
  username: string
  display_name: string
  email: string
  role: string
  is_active: boolean
  avatar_url?: string
}

export interface UserProfilePayload {
  display_name?: string
  email?: string
}

export interface LoginResponse {
  success: boolean
  user?: User
  session_id?: string
  expires_at?: string
  message?: string
  error?: unknown
  market_access_token?: string
  market_refresh_token?: string
  registered?: boolean
  account_state?: string
  next_action?: string
  desktop_access?: boolean
  active_plan_id?: string
  account_tier?: string
  purchase_url?: string
}

export interface RegisterRequest {
  username: string
  password: string
  email?: string
  verification_code?: string
  display_name?: string
  // 账号体系：预算区间（→ account_tier 派生）与行业
  budget_range?: string
  industry_id?: string
}

const LOGIN_RETRY_DELAYS_MS = [1_000, 2_000, 4_000] as const
type AuthOperationOptions = { signal?: AbortSignal; dataProcessingNoticeVersion?: string }

async function withAuthDeadline<T>(operation: (signal: AbortSignal) => Promise<T>, timeoutMs: number, caller?: AbortSignal): Promise<T> {
  caller?.throwIfAborted()
  const controller = new AbortController()
  const abortFromCaller = () => controller.abort(caller?.reason)
  caller?.addEventListener('abort', abortFromCaller, { once: true })
  const timer = setTimeout(() => controller.abort(Object.assign(new Error(`请求超时（>${timeoutMs / 1000}s）`), { status: 0 })), timeoutMs)
  let rejectOnAbort!: () => void
  const aborted = new Promise<never>((_, reject) => {
    rejectOnAbort = () => reject(controller.signal.reason)
    controller.signal.addEventListener('abort', rejectOnAbort, { once: true })
  })
  try {
    return await Promise.race([operation(controller.signal), aborted])
  } finally {
    clearTimeout(timer)
    controller.signal.removeEventListener('abort', rejectOnAbort)
    caller?.removeEventListener('abort', abortFromCaller)
  }
}

function isTransientLoginError(error: unknown): boolean {
  const status = Number((error as { status?: unknown } | null)?.status)
  return status === 0 || status >= 500
}

async function withTransientLoginRetry<T>(operation: () => Promise<T>, signal: AbortSignal): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    signal.throwIfAborted()
    try {
      return await operation()
    } catch (error) {
      signal.throwIfAborted()
      if (!isTransientLoginError(error) || attempt >= LOGIN_RETRY_DELAYS_MS.length) {
        throw error
      }
      await new Promise<void>((resolve, reject) => {
        const cancel = () => { clearTimeout(timer); reject(signal.reason) }
        const timer = setTimeout(() => { signal.removeEventListener('abort', cancel); resolve() }, LOGIN_RETRY_DELAYS_MS[attempt])
        signal.addEventListener('abort', cancel, { once: true })
      })
    }
  }
}

async function clearSessionScopedUiCaches(current: () => boolean): Promise<void> {
  try {
    const { clearDeliverableStatusCache } = await import('@/utils/platformShellApi')
    if (current()) clearDeliverableStatusCache()
  } catch {
    /* ignore */
  }
}

function authOperationOwner(signal: AbortSignal) {
  const epoch = getAuthSessionEpoch()
  const current = () => epoch === getAuthSessionEpoch() && !signal.aborted
  const assertCurrent = () => {
    signal.throwIfAborted()
    if (!current()) throw new DOMException('登录会话已改变', 'AbortError')
  }
  return { current, assertCurrent }
}

function loginRequest(path: string, payload: Record<string, unknown>, options: AuthOperationOptions, retry = true) {
  return withAuthDeadline(async (signal) => {
    invalidateEnterpriseSessionCache()
    clearMarketCredentials()
    const { current, assertCurrent } = authOperationOwner(signal)
    await primeCsrfCookie({ signal })
    const request = () => {
      assertCurrent()
      return api.post<ApiResponse<LoginResponse>>(path, payload, { timeoutMs: 30_000, signal })
    }
    const res = await (retry ? withTransientLoginRetry(request, signal) : request())
    assertCurrent()
    await clearSessionScopedUiCaches(current)
    assertCurrent()
    if (res?.success === true || res?.data?.success === true) markEnterpriseSessionValid()
    return res
  }, 30_000, options.signal)
}

export const authApi = {
  async login(username: string, password: string, accountKind: AccountKind = 'enterprise', invitationCode = '', options: AuthOperationOptions = {}): Promise<ApiResponse<LoginResponse>> {
    return loginRequest('/api/auth/login', {
      username, password, account_kind: accountKind,
      ...(invitationCode.trim() ? { invitation_code: invitationCode.trim() } : {}),
      ...(options.dataProcessingNoticeVersion ? { data_processing_notice_version: options.dataProcessingNoticeVersion } : {}),
    }, options)
  },

  async loginWithPhoneCode(phone: string, code: string, accountKind: AccountKind = 'enterprise', options: AuthOperationOptions = {}): Promise<ApiResponse<LoginResponse>> {
    return loginRequest('/api/auth/login-with-phone-code', {
      phone, code, account_kind: accountKind,
      ...(options.dataProcessingNoticeVersion ? { data_processing_notice_version: options.dataProcessingNoticeVersion } : {}),
    }, options)
  },

  async sendPhoneCode(phone: string): Promise<ApiResponse<{ message?: string }>> {
    await primeCsrfCookie()
    return api.post<ApiResponse<{ message?: string }>>('/api/market/send-phone-code', { phone })
  },

  async getOidcStatus(): Promise<ApiResponse<{ enabled?: boolean }>> {
    return api.get<ApiResponse<{ enabled?: boolean }>>('/api/auth/oidc/status', {}, { timeoutMs: 5_000 })
  },

  async issueAuthQr(
    clientHint = '',
    accountKind = 'enterprise',
  ): Promise<
    ApiResponse<{
      qr_id?: string
      poll_secret?: string
      expires_at?: number
      account_kind?: string
    }>
  > {
    await primeCsrfCookie()
    return api.post('/api/auth/qr/issue', { client_hint: clientHint, account_kind: accountKind })
  },

  async pollAuthQr(qrId: string, pollSecret: string): Promise<ApiResponse<{ status?: string; session_id?: string }>> {
    return api.get('/api/auth/qr/status', {
      qr_id: qrId,
      poll_secret: pollSecret,
    })
  },

  async getSubscriptionStatus(): Promise<ApiResponse<Record<string, unknown>>> {
    return api.get<ApiResponse<Record<string, unknown>>>('/api/auth/subscription/status')
  },

  async updateCompanyBrand(companyBrand: string) {
    return api.post('/api/auth/company-brand', { company_brand: companyBrand })
  },

  async register(payload: RegisterRequest, options: AuthOperationOptions = {}): Promise<ApiResponse<LoginResponse>> {
    return loginRequest('/api/auth/register', { ...payload }, options, false)
  },

  async sendRegisterVerificationCode(email: string): Promise<ApiResponse<{ message?: string }>> {
    await primeCsrfCookie()
    return api.post<ApiResponse<{ message?: string }>>('/api/market/send-register-code', { email })
  },

  async logout(options: AuthOperationOptions = {}): Promise<ApiResponse<void>> {
    clearEnterpriseCsRecovery()
    clearAutoLoginPreference()
    clearMarketCredentials()
    return withAuthDeadline(async (signal) => {
      invalidateEnterpriseSessionCache()
      const { current, assertCurrent } = authOperationOwner(signal)
      await clearSessionScopedUiCaches(current)
      assertCurrent()
      try {
        const { useAccountProfileStore } = await import('@/stores/accountProfile')
        assertCurrent()
        useAccountProfileStore().clear()
      } catch (error) {
        if (!current()) throw error
      }
      await primeCsrfCookie({ signal })
      assertCurrent()
      const res = await api.post<ApiResponse<void>>('/api/auth/logout', {}, { timeoutMs: 10_000, signal })
      assertCurrent()
      return res
    }, 10_000, options.signal)
  },

  async getCurrentUser(options: Pick<RequestOptions, 'signal' | 'timeoutMs'> = {}): Promise<ApiResponse<{ user: User; permissions: string[] }>> {
    return api.get<ApiResponse<{ user: User; permissions: string[] }>>('/api/auth/me', {}, { timeoutMs: 8_000, ...options })
  },

  async getProfile(): Promise<ApiResponse<{ user: User }>> {
    return api.get<ApiResponse<{ user: User }>>('/api/auth/profile', {}, { timeoutMs: 8_000 })
  },

  async updateProfile(payload: UserProfilePayload): Promise<ApiResponse<{ user: User }>> {
    await primeCsrfCookie()
    return api.patch<ApiResponse<{ user: User }>>('/api/auth/profile', payload)
  },

  async uploadAvatar(file: File): Promise<ApiResponse<{ avatar_url: string }>> {
    await primeCsrfCookie()
    const form = new FormData()
    form.append('file', file)
    return api.post<ApiResponse<{ avatar_url: string }>>('/api/auth/profile/avatar', form)
  },

  async validateSession(options: Pick<RequestOptions, 'signal' | 'timeoutMs'> = {}): Promise<ApiResponse<unknown>> {
    return api.get<ApiResponse<unknown>>('/api/auth/session/validate', {}, { timeoutMs: 8_000, ...options })
  },

  async forgotAccount(email: string): Promise<ApiResponse<{ usernames: string[]; found: boolean }>> {
    await primeCsrfCookie()
    return api.post<ApiResponse<{ usernames: string[]; found: boolean }>>('/api/auth/forgot-account', {
      email,
    })
  },

  async sendForgotPasswordCode(email: string): Promise<ApiResponse<unknown>> {
    await primeCsrfCookie()
    return api.post<ApiResponse<unknown>>('/api/auth/forgot-password/send-code', { email })
  },

  async resetForgotPassword(email: string, code: string, newPassword: string): Promise<ApiResponse<{ local_users_updated?: number }>> {
    await primeCsrfCookie()
    return api.post<ApiResponse<{ local_users_updated?: number }>>('/api/auth/forgot-password/reset', {
      email,
      code,
      new_password: newPassword,
    })
  },
}

export default authApi

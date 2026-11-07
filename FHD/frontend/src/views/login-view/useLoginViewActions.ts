import { useI18n } from 'vue-i18n'
import { ApiError } from '@/api'
import { authApi } from '@/api/auth'
import { loadLoginPreferences, saveLoginPreferences } from '@/utils/loginPreferences'
import { DESKTOP_ADMIN_FORBIDDEN_MESSAGE, resolveAdminConsoleLoginUrl } from '@/utils/adminConsoleUrl'
import { isDesktopShell } from '@/utils/desktopShell'
import type { LoginViewState } from './useLoginViewState'
import type { useLoginViewQr } from './useLoginViewQr'

type LoginViewQr = ReturnType<typeof useLoginViewQr>

// LoginView 的登录动作与失败格式化逻辑（与拆分前逐字一致）
export function useLoginViewActions(
  state: LoginViewState,
  options: { qr: LoginViewQr; completeLoginSuccess: (raw: Record<string, unknown>) => Promise<void> },
) {
  const { t } = useI18n()
  const {
    username,
    accountKind,
    password,
    invitationCode,
    loading,
    errorMessage,
    altLoginHint,
    loginMode,
    qrDataUrl,
    rememberPassword,
    autoLogin,
    canSubmit,
    redirectPath,
  } = state
  const { qr, completeLoginSuccess } = options
  const { startQrLogin, stopQrPoll } = qr

  let autoLoginAttempted = false

  function applySavedLoginPreferences() {
    const prefs = loadLoginPreferences()
    rememberPassword.value = prefs.rememberPassword
    autoLogin.value = prefs.autoLogin
    if (prefs.rememberPassword && prefs.username) {
      username.value = prefs.username
      password.value = prefs.password
    }
  }

  async function tryAutoLogin() {
    if (autoLoginAttempted || loading.value || loginMode.value !== 'password') return
    if (!autoLogin.value || !rememberPassword.value) return
    if (!username.value.trim() || !password.value) return
    autoLoginAttempted = true
    await submitLogin()
  }

  function switchLoginMode(mode: 'password' | 'qr') {
    if (mode !== 'password' && mode !== 'qr') return
    loginMode.value = mode
    errorMessage.value = ''
    altLoginHint.value = ''
    if (mode === 'qr') {
      void startQrLogin()
    } else {
      stopQrPoll()
      qrDataUrl.value = ''
    }
  }

  function formatLoginFailurePayload(payload: Record<string, unknown> | null | undefined): string {
    const r = payload && typeof payload === 'object' ? payload : {}
    const errObj = r.error && typeof r.error === 'object' ? (r.error as Record<string, unknown>) : null
    const errorCode =
      (errObj && typeof errObj.code === 'string' && errObj.code.trim()) || (typeof r.error_code === 'string' && r.error_code.trim()) || ''
    const message =
      (typeof r.message === 'string' && r.message.trim()) || (errObj && typeof errObj.message === 'string' && errObj.message.trim()) || ''

    // Login page shows only a short inline reason — no error IDs / diagnostics.
    let out = message || t('login.errLoginFailed')

    if (import.meta.env.DEV && (errorCode === 'MARKET_AUTH_FAILED' || errorCode === 'LOCAL_AUTH_MISMATCH')) {
      out += t('login.devHint')
    }
    return out
  }

  function selectEnterpriseLogin() {
    accountKind.value = 'enterprise'
    altLoginHint.value = ''
    errorMessage.value = ''
  }

  function selectAdminLogin() {
    // 桌面端禁止进管理端（防御：入口已隐藏，仍拦截直调）
    if (isDesktopShell()) {
      errorMessage.value = DESKTOP_ADMIN_FORBIDDEN_MESSAGE
      return
    }
    const url = resolveAdminConsoleLoginUrl(redirectPath.value)
    if (!url) {
      errorMessage.value = DESKTOP_ADMIN_FORBIDDEN_MESSAGE
      return
    }
    window.location.href = url
  }

  let loginAttempt = 0

  async function submitLogin(_event?: Event) {
    if (!canSubmit.value) {
      errorMessage.value = t('login.errNeedUsernamePassword')
      return
    }
    const attempt = ++loginAttempt
    loading.value = true
    errorMessage.value = ''
    const invitation = invitationCode.value.trim()
    const invitationForRequest = invitation && invitation !== password.value ? invitation : ''
    try {
      const result = await authApi.login(username.value.trim(), password.value, accountKind.value, invitationForRequest)
      if (attempt !== loginAttempt) return
      const raw = result as unknown as Record<string, unknown>
      const ok = raw?.success === true || (raw?.data as Record<string, unknown> | undefined)?.success === true
      if (!ok) {
        const nested = (raw?.data as Record<string, unknown> | undefined) || {}
        errorMessage.value = formatLoginFailurePayload({
          ...nested,
          message: raw.message ?? nested.message,
          error_id: raw.error_id ?? nested.error_id,
          error: raw.error ?? nested.error,
        })
        return
      }
      saveLoginPreferences({
        rememberPassword: rememberPassword.value,
        autoLogin: autoLogin.value,
        username: username.value.trim(),
        password: password.value,
      })
      await completeLoginSuccess(raw)
    } catch (error: unknown) {
      if (attempt !== loginAttempt) return
      if (error instanceof ApiError) {
        const d = error.data && typeof error.data === 'object' ? (error.data as Record<string, unknown>) : {}
        errorMessage.value = formatLoginFailurePayload({
          ...d,
          message:
            (typeof d.message === 'string' && d.message) ||
            (typeof (d.error as { message?: string } | undefined)?.message === 'string' && (d.error as { message: string }).message) ||
            error.message,
          error_id: d.error_id,
          error: d.error,
        })
      } else {
        const err = error as {
          response?: { data?: { message?: string; error?: { message?: string } } }
        }
        const data = err.response?.data
        errorMessage.value = data?.error?.message || data?.message || t('login.errLoginFailedRetry')
      }
    } finally {
      if (attempt === loginAttempt) loading.value = false
    }
  }

  function startOidcLogin() {
    window.location.href = '/api/auth/oidc/start'
  }

  return {
    applySavedLoginPreferences,
    tryAutoLogin,
    switchLoginMode,
    formatLoginFailurePayload,
    selectEnterpriseLogin,
    selectAdminLogin,
    submitLogin,
    startOidcLogin,
  }
}

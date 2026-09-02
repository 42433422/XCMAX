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
    loading,
    errorMessage,
    altLoginHint,
    loginMode,
    phone,
    smsCode,
    sendingCode,
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

  async function sendPhoneCode() {
    if (phone.value.trim().length < 5) {
      errorMessage.value = t('login.errInvalidPhone')
      return
    }
    sendingCode.value = true
    errorMessage.value = ''
    try {
      const res = await authApi.sendPhoneCode(phone.value.trim())
      altLoginHint.value = String((res as { message?: string }).message || t('login.errCodeSent'))
    } catch (error: unknown) {
      errorMessage.value = error instanceof ApiError ? error.message : t('login.errSendCodeFailed')
    } finally {
      sendingCode.value = false
    }
  }

  function switchLoginMode(mode: 'password' | 'phone' | 'qr') {
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
    const errorId = typeof r.error_id === 'string' && r.error_id.trim() ? r.error_id.trim() : ''

    let out = ''
    if (message) {
      out = message
      if (errorId && !out.includes(errorId)) {
        out = `${out}${t('login.errIdSuffix', { id: errorId })}`
      }
    } else if (errorId) {
      out = t('login.errWithId', { id: errorId })
    } else {
      out = t('login.errLoginFailed')
    }

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

  async function submitLogin() {
    if (!canSubmit.value) {
      errorMessage.value = loginMode.value === 'phone' ? t('login.errNeedPhoneAndCode') : t('login.errNeedUsernamePassword')
      return
    }
    loading.value = true
    errorMessage.value = ''
    try {
      const result =
        loginMode.value === 'phone'
          ? await authApi.loginWithPhoneCode(phone.value.trim(), smsCode.value.trim(), accountKind.value)
          : await authApi.login(username.value.trim(), password.value, accountKind.value)
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
      loading.value = false
    }
  }

  function startOidcLogin() {
    window.location.href = '/api/auth/oidc/start'
  }

  return {
    applySavedLoginPreferences,
    tryAutoLogin,
    sendPhoneCode,
    switchLoginMode,
    formatLoginFailurePayload,
    selectEnterpriseLogin,
    selectAdminLogin,
    submitLogin,
    startOidcLogin,
  }
}

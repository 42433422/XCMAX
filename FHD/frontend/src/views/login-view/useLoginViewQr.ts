import QRCode from 'qrcode'
import { useI18n } from 'vue-i18n'
import { ApiError } from '@/api'
import { authApi } from '@/api/auth'
import type { LoginViewState } from './useLoginViewState'

// LoginView 的扫码登录与轮询逻辑（与拆分前逐字一致）
export function useLoginViewQr(
  state: LoginViewState,
  options: { completeLoginSuccess: (raw: Record<string, unknown>) => Promise<void> },
) {
  const { t } = useI18n()
  const { accountKind, errorMessage, qrDataUrl, qrPollTimer, qrExpiresAt, qrId, qrPollSecret, qrCountdown } = state
  const { completeLoginSuccess } = options

  function stopQrPoll() {
    if (qrPollTimer.value != null) {
      window.clearInterval(qrPollTimer.value)
      qrPollTimer.value = null
    }
  }

  async function startQrLogin() {
    stopQrPoll()
    errorMessage.value = ''
    qrDataUrl.value = ''
    try {
      const res = await authApi.issueAuthQr(navigator.userAgent.slice(0, 120), accountKind.value)
      const data = (res as { data?: Record<string, unknown> }).data ?? (res as unknown as Record<string, unknown>)
      qrId.value = String(data.qr_id || '')
      qrPollSecret.value = String(data.poll_secret || '')
      qrExpiresAt.value = Number(data.expires_at || 0)
      const qrAccountKind = String(data.account_kind || accountKind.value || 'enterprise')
      const payload = `xcagi://auth-qr?qr_id=${encodeURIComponent(qrId.value)}` + `&account_kind=${encodeURIComponent(qrAccountKind)}`
      qrDataUrl.value = await QRCode.toDataURL(payload, { width: 220, margin: 1 })
      qrPollTimer.value = window.setInterval(() => void pollQrStatus(), 2000)
    } catch (error: unknown) {
      errorMessage.value = error instanceof ApiError ? error.message : t('login.errQrGenerateFailed')
    }
  }

  async function pollQrStatus() {
    if (!qrId.value || !qrPollSecret.value) return
    if (qrCountdown.value <= 0) {
      stopQrPoll()
      errorMessage.value = t('login.errQrExpired')
      return
    }
    try {
      const res = await authApi.pollAuthQr(qrId.value, qrPollSecret.value)
      const data = (res as { data?: Record<string, unknown> }).data || {}
      if (data.status === 'confirmed') {
        stopQrPoll()
        await completeLoginSuccess({ success: true, ...data } as Record<string, unknown>)
      } else if (data.status === 'expired') {
        stopQrPoll()
        errorMessage.value = t('login.errQrExpiredRetry')
      }
    } catch {
      /* ignore transient poll errors */
    }
  }

  return { stopQrPoll, startQrLogin, pollQrStatus }
}

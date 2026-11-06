import { showAppToast } from '@/composables/useAppToast'
import { readCsrfTokenFromCookie } from '@/utils/csrfCookie'
import { productErrorMessage } from '@/utils/productErrorMessage'
import { createTraceId, publishStabilityNotice } from '@/utils/networkStability'
import { buildFullApiUrl, registerSessionRefresh } from './core'

/** 生产只安装失败提示；实验刷新与故障注入须显式启用 VITE_STABILITY_LAB。 */
export function installStabilityClient(): void {
  window.addEventListener('xcagi:stability-notice', (event) => {
    const message = String((event as CustomEvent<{ message?: string }>).detail?.message || '')
    if (!message) return
    publishStabilityNotice(message)
    showAppToast(message, 'error', { duration: 8000 })
  })

  if (import.meta.env.VITE_STABILITY_LAB !== '1') return

  registerSessionRefresh(async () => {
    const refresh = window.localStorage.getItem('xcagi_stability_refresh') || ''
    if (!refresh) return false
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Request-ID': createTraceId(),
    }
    const csrf = readCsrfTokenFromCookie()
    if (csrf) headers['X-CSRF-Token'] = csrf
    const response = await fetch(buildFullApiUrl('/api/stability/lab/refresh'), {
      method: 'POST',
      credentials: 'include',
      headers,
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (!response.ok) return false
    const body = await response.json() as { success?: boolean; refresh_token?: string }
    if (body.refresh_token) window.localStorage.setItem('xcagi_stability_refresh', body.refresh_token)
    return body.success === true
  })

  void fetch(buildFullApiUrl('/api/stability/ui-notice'), { credentials: 'include' })
    .then((response) => response.json())
    .then((body: { raw?: string }) => {
      if (!body?.raw) return
      const message = productErrorMessage(body.raw, '操作未成功')
      publishStabilityNotice(message)
      showAppToast(message, 'error', { duration: 8000 })
    })
    .catch(() => undefined)
}

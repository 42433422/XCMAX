import { showAppToast } from '@/composables/useAppToast'
import { readCsrfTokenFromCookie } from '@/utils/csrfCookie'
import { productErrorMessage } from '@/utils/productErrorMessage'
import { createTraceId, publishStabilityNotice } from '@/utils/networkStability'
import { buildFullApiUrl, registerSessionRefresh } from './core'

/** 把实验会话的刷新并进全局单飞，并在页面上显示分类后的失败文案。 */
export function installStabilityClient(): void {
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

  window.addEventListener('xcagi:stability-notice', (event) => {
    const message = String((event as CustomEvent<{ message?: string }>).detail?.message || '')
    if (!message) return
    publishStabilityNotice(message)
    showAppToast(message, 'error', { duration: 8000 })
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

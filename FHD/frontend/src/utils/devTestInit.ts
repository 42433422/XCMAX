import api from '@/api'
import { resetProductFlowState } from '@/constants/productFlow'
import { patchWorkspacePrefs } from '@/utils/workspacePrefsApi'

const ONBOARDING_DRIVER_TUTORIAL_KEY = 'xcagi_onboarding_driver_tutorial_completed'

export async function resetHostOnboardingForTest(): Promise<void> {
  resetProductFlowState()
  try {
    localStorage.removeItem(ONBOARDING_DRIVER_TUTORIAL_KEY)
  } catch {
    /* ignore */
  }
  try {
    await patchWorkspacePrefs({
      product_flow_completed: false,
      host_pack_acknowledged: false,
    })
  } catch {
    /* 未登录或离线时仅清本地缓存 */
  }
}

export async function bootstrapDesktopDatabase(): Promise<{ steps?: string[]; message?: string }> {
  const res = await api.post<{ success?: boolean; steps?: string[]; message?: string; detail?: string }>(
    '/api/desktop/bootstrap-db',
  )
  if (!res?.success) {
    throw new Error(String(res?.message || res?.detail || '初始化失败'))
  }
  return { steps: res.steps, message: res.message }
}

export function openAssistantTutorialTab(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(
    new CustomEvent('xcagi:tutorial:set-assistant-tab', { detail: { open: true, tab: 'tutorial' } }),
  )
}

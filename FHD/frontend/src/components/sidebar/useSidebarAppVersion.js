/**
 * 侧边栏应用版本徽标：/api/health 版本 + package.json 兜底（拆分自 components/Sidebar.vue，行为保持一致）。
 */
import { computed, ref } from 'vue'
import packageJson from '../../../package.json'

export function displayVersion(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  return text.toLowerCase().startsWith('v') ? text : `v${text}`
}

export function useSidebarAppVersion({ shouldShowAdminDeployStatus }) {
  const healthAppVersion = ref('')

  const sidebarAppVersionText = computed(() => {
    if (shouldShowAdminDeployStatus.value) return ''
    return displayVersion(healthAppVersion.value || packageJson.version || '')
  })

  const sidebarAppVersionTitle = computed(() => {
    const ver = String(healthAppVersion.value || packageJson.version || '').trim()
    return ver ? `当前版本 ${displayVersion(ver)}` : '当前应用版本'
  })

  async function refreshHealthAppVersion() {
    if (shouldShowAdminDeployStatus.value) return
    try {
      const res = await fetch('/api/health', { credentials: 'same-origin' })
      if (!res.ok) return
      const data = await res.json()
      healthAppVersion.value = String(data?.version || '').trim()
    } catch {
      /* 健康检查失败时回退 package.json 版本 */
    }
  }

  return {
    sidebarAppVersionText,
    sidebarAppVersionTitle,
    refreshHealthAppVersion,
  }
}

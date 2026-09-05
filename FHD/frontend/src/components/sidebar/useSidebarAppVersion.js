/**
 * 侧边栏应用版本徽标：/api/health 版本 + package.json 兜底（拆分自 components/Sidebar.vue，行为保持一致）。
 */
import { computed, ref } from 'vue'
import { buildFullApiUrl } from '@/api/core'
import packageJson from '../../../package.json'
import { runtimeHealthPresentation } from './runtimeHealthPresentation'

export function displayVersion(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  return text.toLowerCase().startsWith('v') ? text : `v${text}`
}

export function useSidebarAppVersion({ shouldShowAdminDeployStatus }) {
  const healthAppVersion = ref('')
  const healthData = ref(null)
  const connection = ref('checking')
  const runtimeHealth = computed(() => runtimeHealthPresentation(healthData.value, connection.value))
  let pollTimer = null
  let controller = null
  let pendingRequest = null
  let stopped = false

  const sidebarAppVersionText = computed(() => {
    if (shouldShowAdminDeployStatus.value) return ''
    return displayVersion(healthAppVersion.value || packageJson.version || '')
  })

  const sidebarAppVersionTitle = computed(() => {
    const ver = String(healthAppVersion.value || packageJson.version || '').trim()
    return ver ? `当前版本 ${displayVersion(ver)}` : '当前应用版本'
  })

  function refreshHealthAppVersion() {
    if (pendingRequest) return pendingRequest
    controller = new AbortController()
    const requestController = controller
    const timeout = setTimeout(() => requestController.abort(), 8_000)
    pendingRequest = (async () => {
      try {
        const res = await fetch(buildFullApiUrl('/api/health'), {
          credentials: 'include', cache: 'no-store', signal: requestController.signal,
        })
        if (!res.ok && res.status !== 503) throw new Error('Health request failed')
        const data = await res.json()
        if (stopped) return
        healthData.value = data
        connection.value = 'ready'
        healthAppVersion.value = String(data?.version || '').trim()
      } catch {
        if (!stopped) connection.value = 'offline'
      } finally {
        clearTimeout(timeout)
        controller = null
        pendingRequest = null
      }
    })()
    return pendingRequest
  }

  function refreshWhenVisible() {
    if (!document.hidden) void refreshHealthAppVersion()
  }

  function startHealthPolling() {
    stopped = false
    if (pollTimer !== null) return
    void refreshHealthAppVersion()
    pollTimer = setInterval(refreshWhenVisible, 30_000)
    document.addEventListener('visibilitychange', refreshWhenVisible)
    window.addEventListener('online', refreshWhenVisible)
  }

  function stopHealthPolling() {
    stopped = true
    if (pollTimer !== null) clearInterval(pollTimer)
    pollTimer = null
    controller?.abort()
    document.removeEventListener('visibilitychange', refreshWhenVisible)
    window.removeEventListener('online', refreshWhenVisible)
  }

  return {
    sidebarAppVersionText,
    sidebarAppVersionTitle,
    refreshHealthAppVersion,
    runtimeHealth,
    startHealthPolling,
    stopHealthPolling,
  }
}

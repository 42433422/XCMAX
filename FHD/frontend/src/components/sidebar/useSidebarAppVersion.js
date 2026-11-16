/**
 * 侧边栏应用版本徽标：/api/health 版本 + package.json 兜底（拆分自 components/Sidebar.vue，行为保持一致）。
 */
import { computed, ref } from 'vue'
import { buildFullApiUrl } from '@/api/core'
import packageJson from '../../../package.json'
import { modelPathStatus } from './modelPathHealth'
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
  const lastCheckedAt = ref(null)
  const runtimeHealth = computed(() => runtimeHealthPresentation(healthData.value, connection.value, modelPathStatus.value))
  let pollTimer = null
  let controller = null
  let pendingRequest = null
  let stopped = false
  let lifecycle = 0
  let requestTimeout = null
  let failureCount = 0
  let nextRetryAt = 0
  let retryTimer = null
  let lastApiReachableAt = null
  let lastSuccessAt = null
  const HEALTH_GRACE_MS = 90_000
  const runtimeHealthCheck = computed(() => {
    if (lastCheckedAt.value === null) return { iso: '', text: '尚未检测', title: '尚未检测' }
    const date = new Date(lastCheckedAt.value)
    return {
      iso: date.toISOString(),
      text: `最近检测 ${date.toLocaleTimeString('zh-CN', { hour12: false })}`,
      title: `最近检测 ${date.toLocaleString('zh-CN', { hour12: false })}`,
    }
  })

  const sidebarAppVersionText = computed(() => {
    if (shouldShowAdminDeployStatus.value) return ''
    return displayVersion(healthAppVersion.value || packageJson.version || '')
  })

  const sidebarAppVersionTitle = computed(() => {
    const ver = String(healthAppVersion.value || packageJson.version || '').trim()
    return ver ? `当前版本 ${displayVersion(ver)}` : '当前应用版本'
  })

  function refreshHealthAppVersion({ respectBackoff = false } = {}) {
    if (stopped) return Promise.resolve()
    if (pendingRequest) return pendingRequest
    if (respectBackoff && Date.now() < nextRetryAt) return Promise.resolve()
    const epoch = lifecycle
    controller = new AbortController()
    const requestController = controller
    const timeout = setTimeout(() => requestController.abort(), 8_000)
    requestTimeout = timeout
    pendingRequest = Promise.resolve().then(async () => {
      try {
        if (stopped || epoch !== lifecycle) return
        const res = await fetch(buildFullApiUrl('/api/health?lite=1'), {
          credentials: 'include', cache: 'no-store', signal: requestController.signal,
        })
        if (stopped || epoch !== lifecycle) return
        if (requestController.signal.aborted) throw new Error('Health request timed out')
        if (res.status === 502 || res.status === 504) {
          healthData.value = { status: 'unhealthy', runtime: { blockers: [`http_${res.status}`] } }
          connection.value = 'ready'
          healthAppVersion.value = ''
          failureCount = Math.min(failureCount + 1, 4)
          nextRetryAt = Date.now() + 8_000
          lastCheckedAt.value = Date.now()
          scheduleHealthRetry()
          return
        }
        if (!res.ok && res.status !== 503) throw new Error('Health request failed')
        const data = await res.json()
        if (stopped || epoch !== lifecycle) return
        if (requestController.signal.aborted) throw new Error('Health request timed out')
        healthData.value = data
        connection.value = 'ready'
        healthAppVersion.value = String(data?.version || '').trim()
        failureCount = 0
        nextRetryAt = 0
        lastSuccessAt = Date.now()
        lastCheckedAt.value = Date.now()
      } catch {
        if (!stopped && epoch === lifecycle) {
          const recentlyHealthy = lastSuccessAt !== null && Date.now() - lastSuccessAt < HEALTH_GRACE_MS
          // One blip while the shell is navigating or the chat stream is busy is not an outage.
          if (recentlyHealthy && failureCount === 0) {
            failureCount = 1
            nextRetryAt = Date.now() + 8_000
            scheduleHealthRetry()
          } else {
            connection.value = lastApiReachableAt !== null && Date.now() - lastApiReachableAt < 30_000 ? 'reachable' : 'offline'
            lastCheckedAt.value = Date.now()
            failureCount = Math.min(failureCount + 1, 4)
            nextRetryAt = Date.now() + Math.min(30_000 * 2 ** failureCount, 300_000)
          }
        }
      } finally {
        clearTimeout(timeout)
        if (epoch === lifecycle) {
          controller = null
          requestTimeout = null
          pendingRequest = null
        }
      }
    })
    return pendingRequest
  }

  function scheduleHealthRetry() {
    if (retryTimer !== null) clearTimeout(retryTimer)
    if (stopped) return
    const delay = Math.max(0, nextRetryAt - Date.now())
    retryTimer = setTimeout(() => {
      retryTimer = null
      void refreshHealthAppVersion({ respectBackoff: true })
    }, delay)
  }

  function refreshWhenVisible() {
    if (!document.hidden) void refreshHealthAppVersion({ respectBackoff: true })
  }

  /** Clear false offline after any successful API (e.g. voice transcribe) without waiting for /api/health. */
  function markApiReachable() {
    if (stopped) return
    lastApiReachableAt = Date.now()
    if (connection.value === 'offline' || connection.value === 'checking') {
      connection.value = 'reachable'
      failureCount = 0
      nextRetryAt = 0
      lastCheckedAt.value = Date.now()
    }
  }

  function onApiReachableEvent() {
    const wasUnconfirmed = connection.value !== 'ready'
    markApiReachable()
    // Soft refresh health in background to resync version/degraded reasons.
    if (wasUnconfirmed) void refreshHealthAppVersion({ respectBackoff: false })
  }

  function startHealthPolling() {
    stopped = false
    if (pollTimer !== null) return
    failureCount = 0
    nextRetryAt = 0
    void refreshHealthAppVersion()
    pollTimer = setInterval(refreshWhenVisible, 30_000)
    document.addEventListener('visibilitychange', refreshWhenVisible)
    window.addEventListener('online', refreshWhenVisible)
    window.addEventListener('xcagi:api-reachable', onApiReachableEvent)
  }

  function stopHealthPolling() {
    stopped = true
    lastApiReachableAt = null
    lifecycle += 1
    if (pollTimer !== null) clearInterval(pollTimer)
    pollTimer = null
    if (retryTimer !== null) clearTimeout(retryTimer)
    retryTimer = null
    controller?.abort()
    controller = null
    pendingRequest = null
    if (requestTimeout !== null) clearTimeout(requestTimeout)
    requestTimeout = null
    document.removeEventListener('visibilitychange', refreshWhenVisible)
    window.removeEventListener('online', refreshWhenVisible)
    window.removeEventListener('xcagi:api-reachable', onApiReachableEvent)
  }

  return {
    sidebarAppVersionText,
    sidebarAppVersionTitle,
    refreshHealthAppVersion,
    runtimeHealth,
    runtimeHealthCheck,
    startHealthPolling,
    stopHealthPolling,
    markApiReachable,
  }
}

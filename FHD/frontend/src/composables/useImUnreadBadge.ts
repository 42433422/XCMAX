import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { fetchImUnreadTotal } from '@/api/im'
import { XCMAX_SYNC_IM_MESSAGE_EVENT, XCMAX_SYNC_IM_READ_EVENT } from '@/composables/useXcmaxSync'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'

const imUnreadTotal = ref(0)
let pollTimer: ReturnType<typeof setInterval> | null = null
let loggedOut = false

function isPublicRoute(name: unknown): boolean {
  const n = String(name || '')
  return n === 'login' || n.startsWith('login-') || n === 'lan-gate' || n === 'product-onboarding'
}

export function useImUnreadBadge() {
  const route = useRoute()

  function stopPolling(): void {
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = null
  }

  function onLoggedOut(): void {
    loggedOut = true
    imUnreadTotal.value = 0
    stopPolling()
  }

  async function refreshImUnreadTotal(): Promise<void> {
    // 公共页或已确认未登录时不再请求，避免未读接口 401 轮询。
    if (loggedOut || isPublicRoute(route.name) || isAdminConsoleSpa()) {
      imUnreadTotal.value = 0
      return
    }
    // fetchImUnreadTotal 内部已吞掉所有异常并返回 0
    const total = await fetchImUnreadTotal()
    imUnreadTotal.value = total
    try {
      if (window.xcagiDesktop?.setBadge) {
        await window.xcagiDesktop.setBadge(total)
      }
    } catch {
      /* ignore */
    }
  }

  function onSyncImActivity(): void {
    void refreshImUnreadTotal()
  }

  watch(
    () => route.name,
    (name, previous) => {
      if (!loggedOut || !isPublicRoute(previous) || isPublicRoute(name)) return
      loggedOut = false
      void refreshImUnreadTotal()
      if (!pollTimer) pollTimer = setInterval(() => void refreshImUnreadTotal(), 30_000)
    },
  )

  onMounted(() => {
    void refreshImUnreadTotal()
    pollTimer = setInterval(() => void refreshImUnreadTotal(), 30_000)
    window.addEventListener(XCMAX_SYNC_IM_MESSAGE_EVENT, onSyncImActivity)
    window.addEventListener(XCMAX_SYNC_IM_READ_EVENT, onSyncImActivity)
    window.addEventListener('xcagi:session-unauthorized', onLoggedOut)
  })
  onUnmounted(() => {
    stopPolling()
    window.removeEventListener(XCMAX_SYNC_IM_MESSAGE_EVENT, onSyncImActivity)
    window.removeEventListener(XCMAX_SYNC_IM_READ_EVENT, onSyncImActivity)
    window.removeEventListener('xcagi:session-unauthorized', onLoggedOut)
  })

  return { imUnreadTotal, refreshImUnreadTotal }
}

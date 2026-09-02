// 拆分自 App.vue：全局状态刷新与路由后置钩子逻辑（逻辑逐字迁移，行为不变）。
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useNotificationStore } from '../stores/notifications'
import { useWalletStore } from '../stores/wallet'

export function useAppGlobalState() {
  const router = useRouter()
  const authStore = useAuthStore()
  const walletStore = useWalletStore()
  const notificationStore = useNotificationStore()

  const initialPath = String(router.currentRoute.value.path || '/')
  const isHome = ref(initialPath === '/about')
  const isEmployeeWorkbench = ref(
    initialPath.startsWith('/workbench/employee') ||
    initialPath.startsWith('/workbench/shell') ||
    initialPath.startsWith('/workbench/unified') ||
    initialPath.startsWith('/workbench/mod/'),
  )

  function checkHome() {
    const path = String(router.currentRoute.value.path || '/')
    isHome.value = path === '/about'
    isEmployeeWorkbench.value =
      path.startsWith('/workbench/employee') ||
      path.startsWith('/workbench/shell') ||
      path.startsWith('/workbench/unified') ||
      path.startsWith('/workbench/mod/')
  }

  async function refreshGlobalState() {
    await authStore.refreshSession()
    // 首次 /api/auth/me 若遇 502/网络抖动，user 会被清空但 JWT 仍保留，顶栏会误显示「登录」；短延迟后强刷一次
    if (!authStore.isLoggedIn && authStore.hasToken()) {
      await new Promise((r) => setTimeout(r, 350))
      await authStore.refreshSession(true)
    }
    if (authStore.isLoggedIn) {
      await Promise.all([walletStore.refreshBalance(), notificationStore.refreshUnread()])
    } else {
      walletStore.clear()
      notificationStore.clear()
    }
  }

  // afterEach 去抖：checkHome 轻量立即执行；refreshGlobalState（3 个网络请求）
  // 推迟到浏览器空闲再执行，并在 1500ms 内对相同 path 去重，避免路由切换期间
  // 同时占主线程。
  let _lastRefreshPath = ''
  let _lastRefreshAt = 0
  let _refreshIdleId: ReturnType<typeof setTimeout> | null = null

  function _scheduleGlobalRefresh() {
    const path = String(router.currentRoute.value.path || '/')
    const now = Date.now()
    // 1500ms 内同路径不重复触发
    if (path === _lastRefreshPath && now - _lastRefreshAt < 1500) return
    if (_refreshIdleId !== null) { clearTimeout(_refreshIdleId); _refreshIdleId = null }
    const run = () => {
      _refreshIdleId = null
      _lastRefreshPath = String(router.currentRoute.value.path || '/')
      _lastRefreshAt = Date.now()
      void refreshGlobalState()
    }
    if (typeof window.requestIdleCallback === 'function') {
      const id = window.requestIdleCallback(run, { timeout: 2000 })
      // 用 setTimeout 包装确保可清理
      _refreshIdleId = setTimeout(() => { window.cancelIdleCallback(id) }, 3000)
      // 在 idle 完成后清除
      window.requestIdleCallback(() => {
        if (_refreshIdleId !== null) { clearTimeout(_refreshIdleId); _refreshIdleId = null }
      })
    } else {
      // 不支持 requestIdleCallback 的环境（如 Safari < 15.4）降级到 300ms delay
      _refreshIdleId = setTimeout(run, 300)
    }
  }

  return {
    isHome,
    isEmployeeWorkbench,
    checkHome,
    refreshGlobalState,
    _scheduleGlobalRefresh,
  }
}

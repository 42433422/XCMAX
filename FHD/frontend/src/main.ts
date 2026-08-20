import { createApp } from 'vue'
import { createPinia } from 'pinia'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import './fhd/installFetchDbReadToken'
import { useAppShellStore } from '@/stores/appShell'
import {
  bootstrapAdminConsoleShellDefaults,
  bootstrapEditionDefaults,
  bootstrapEnterpriseShellDefaults,
} from '@/constants/platformShellMode'

bootstrapEditionDefaults()
bootstrapEnterpriseShellDefaults()
bootstrapAdminConsoleShellDefaults()

import App from './App.vue'
import router from './router'
import { bindTutorialRouter } from '@/stores/tutorial'
import { registerAllModRoutesFromGlob, registerModRoutes } from './router/registerModRoutes'

bindTutorialRouter(router)
import { fetchModRoutesPayloadShared } from './utils/modRoutesSharedFetch'
import { CLIENT_MODS_UI_OFF_KEY } from '@/stores/mods'
import { applySidebarThemeFromStorage } from './utils/sidebarTheme'
import { installClientConsoleBridge } from './utils/clientDebugLog'
import { initServiceWorker, unregisterStaleServiceWorkers } from './utils/serviceWorker'
import { bootstrapHostConfig } from '@/stores/hostConfig'

import './styles/tokens.css'
import './styles/css/base.css'
import './styles/css/components/sidebar.css'
import './styles/css/components/chat.css'
import './styles/css/components/tables.css'
import './styles/css/components/modals.css'
import './styles/css/components/ui-components.css'
import './styles/css/animations/transitions.css'
import './styles/css/animations/ui-effects.css'
import './styles/css/office-theme.css'
import 'font-awesome/css/font-awesome.min.css'

// Window globals are kept for backward compatibility; prefer using the Pinia appShell store.

function readVanillaNoModUi(): boolean {
  try {
    return localStorage.getItem(CLIENT_MODS_UI_OFF_KEY) === '1'
  } catch {
    return false
  }
}

function browserFullPath(): string {
  if (typeof window === 'undefined' || !window.location) return '/'
  const base = String(import.meta.env.BASE_URL || '/').replace(/\/$/, '')
  let pathname = window.location.pathname || '/'
  if (base && base !== '/' && pathname.startsWith(`${base}/`)) {
    pathname = pathname.slice(base.length) || '/'
  } else if (base && base !== '/' && pathname === base) {
    pathname = '/'
  }
  return `${pathname}${window.location.search || ''}${window.location.hash || ''}`
}

function scheduleRouterAddressSync(reason: string): void {
  if (typeof window === 'undefined') return
  const syncOnce = async () => {
    const target = browserFullPath()
    if (!target || target === router.currentRoute.value.fullPath) return
    const resolved = router.resolve(target)
    if (!resolved.matched.length) return
    try {
      await router.replace(target)
    } catch (e) {
      if (import.meta.env.DEV) {
        console.warn(`[bootstrap] route address sync failed (${reason}):`, e)
      }
    }
  }
  void syncOnce()
  window.setTimeout(() => {
    void syncOnce()
  }, 500)
  window.setTimeout(() => {
    void syncOnce()
  }, 1500)
}

/**
 * 后台分批预取静态路由的懒加载 chunk，使侧栏切换页面时无需等待 JS 拉取，消除「卡顿」。
 * 每次预取 4 个，交还主线程避免启动瞬间雪崩；仅预取非公开、非裸壳的业务/核心页面。
 */
function prefetchStaticRouteChunks(): void {
  const routes = router.getRoutes()
  const jobs = routes
    .filter((r) => r.meta?.publicAccess !== true && r.meta?.hideChrome !== true)
    .map((r) => r.components?.default)
    .filter((c): c is () => Promise<unknown> => typeof c === 'function')
  if (!jobs.length) return
  const idle = (cb: () => void): void => {
    const win = window as typeof window & {
      requestIdleCallback?: (task: () => void) => unknown
    }
    if (win.requestIdleCallback) win.requestIdleCallback(cb)
    else window.setTimeout(cb, 60)
  }
  let index = 0
  const step = (): void => {
    const end = Math.min(index + 4, jobs.length)
    for (; index < end; index++) {
      jobs[index]().catch(() => {})
    }
    if (index < jobs.length) idle(step)
  }
  step()
}

/**
 * 与 mount 并行预取 Mod 路由，避免在 bootstrap 里 await 网络导致整页长时间不挂载（用户感觉「卡死」）。
 * 深链直达 Mod 页时若此请求晚于首跳，仍可由 modsStore.initialize 内 registerModRoutes 补齐。
 */
async function bootstrap() {
  bootstrapEditionDefaults()
  void bootstrapHostConfig()
  applySidebarThemeFromStorage()
  installClientConsoleBridge()

  if (typeof window !== 'undefined') {
    const host = window.location.hostname
    const isLocalHost = import.meta.env.DEV || host === '127.0.0.1' || host === 'localhost'

    if (isLocalHost) {
      // 打包页走 127.0.0.1:5000 时 main 不会注册 SW，但必须清掉历史残留，否则会劫持 fetch 并报 206 cache 错
      void unregisterStaleServiceWorkers()
    } else {
      initServiceWorker()
        .then((swStatus) => {
          if (swStatus.registered) {
            console.log(`[Bootstrap] Service Worker ready (offline: ${swStatus.offline})`)
          }
        })
        .catch(() => {})
    }
  }

  const app = createApp(App)
  const pinia = createPinia()

  app.config.errorHandler = (err, _instance, info) => {
    console.error('[Vue]', info || 'unknown hook', err)
  }
  window.addEventListener('unhandledrejection', (event) => {
    console.error('[unhandledrejection]', event.reason)
  })

  app.use(pinia)
  const { default: i18n } = await import('./i18n')
  app.use(i18n)
  try {
    const shell = useAppShellStore()
    shell.setAppActive(true)
    shell.setChatOwnsInput(true)
    try {
      window.__VUE_APP_ACTIVE__ = !!shell.appActive
    } catch {
      // ignore
    }
  } catch {
    // ignore if store import fails in legacy environments
  }

  app.use(router)

  for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
    app.component(key, component)
  }

  app.mount('#app')

  if (typeof performance !== 'undefined' && performance.mark) {
    performance.mark('bootstrap_mount')
  }

  // 侧栏切换页面「卡顿」根因之一：路由组件均为懒加载 chunk，首次进入某页需现拉 JS。
  // 桌面壳（localhost）下后台分批预取静态路由 chunk，让点击即切、无首访拉取等待。
  if (typeof window !== 'undefined') {
    const host = window.location.hostname
    if (import.meta.env.DEV || host === '127.0.0.1' || host === 'localhost') {
      prefetchStaticRouteChunks()
    }
  }

  if (!readVanillaNoModUi()) {
    void (async () => {
      try {
        await registerAllModRoutesFromGlob(router)
        scheduleRouterAddressSync('glob')
      } catch (e) {
        console.warn('[bootstrap] mod routes (glob) after mount failed:', e)
      }
    })()
  }

  void (async () => {
    if (readVanillaNoModUi()) return
    try {
      const entries = await fetchModRoutesPayloadShared()
      if (entries?.length) {
        await registerModRoutes(router, entries)
        scheduleRouterAddressSync('api')
      }
    } catch (e) {
      console.warn('[bootstrap] Mod routes (API) register failed:', e)
    }
  })()
}

void bootstrap()

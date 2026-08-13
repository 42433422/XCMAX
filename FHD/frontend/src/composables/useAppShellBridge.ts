import type { Router } from 'vue-router'
import { navigateFromSidebarKey } from '@/utils/sidebarNavigation'

/**
 * 集中管理 App 壳层对 window 的 legacy 桥接，避免 App.vue 散落赋值。
 */
export function useAppShellBridge(router: Router) {
  let switchViewEvent: ((event: Event) => void) | null = null
  let sandboxMessageHandler: ((e: MessageEvent) => void) | null = null

  function installSwitchViewBridge() {
    switchViewEvent = (event: Event) => {
      const view = (event as CustomEvent<{ view?: string }>).detail?.view
      if (view) {
        console.log('[AppShellBridge] xcagi:switch-view received, navigating to:', view)
        void navigateFromSidebarKey(router, view)
      }
    }
    window.addEventListener('xcagi:switch-view', switchViewEvent)
  }

  function installSandboxBridge(isSandboxMode: boolean) {
    if (!isSandboxMode) return
    sandboxMessageHandler = (e: MessageEvent) => {
      if (e.data?.type === 'sandbox:navigate' && typeof e.data.path === 'string') {
        router.push(e.data.path)
      }
    }
    window.addEventListener('message', sandboxMessageHandler)
    window.parent.postMessage({ type: 'sandbox:ready' }, '*')
  }

  function bindLegacyUploadHooks(routeName: string) {
    const shouldBind = routeName === 'chat' || routeName === ''
    if (!shouldBind) return

    const bindOnce = (id: string, eventName: string, handler: () => void) => {
      const el = document.getElementById(id)
      if (!el) return
      if (el.getAttribute('data-xcagi-bound') === '1') return
      el.setAttribute('data-xcagi-bound', '1')
      el.addEventListener(eventName, handler)
    }

    bindOnce('fileUploadEntry', 'click', () => {
      try {
        const openImport = (window as Window & { openImportWindow?: () => void }).openImportWindow
        if (typeof openImport === 'function') {
          openImport()
        } else {
          console.warn('[AppShellBridge] openImportWindow not found on window')
        }
      } catch (err) {
        console.warn('[AppShellBridge] fileUploadEntry click failed:', err)
      }
    })

    bindOnce('chooseFileBtn', 'click', () => {
      const fileInput = document.getElementById('fileInput')
      if (fileInput) fileInput.click()
    })
  }

  function uninstall() {
    if (switchViewEvent) {
      window.removeEventListener('xcagi:switch-view', switchViewEvent)
      switchViewEvent = null
    }
    if (sandboxMessageHandler) {
      window.removeEventListener('message', sandboxMessageHandler)
      sandboxMessageHandler = null
    }
  }

  return {
    installSwitchViewBridge,
    installSandboxBridge,
    bindLegacyUploadHooks,
    uninstall,
  }
}

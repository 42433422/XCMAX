import type { Router } from 'vue-router'
import { isClientModeTiersUiEnabled } from '@/constants/clientModeTiers'

type ProModeController = {
  readProModeStateFromDom: () => boolean
  isProMode: { value: boolean }
  hasLegacyProModeRuntime: () => boolean
  resolveModProEntryPath: () => string
  enterModProMode: () => Promise<void>
  exitModProMode: () => Promise<void>
  syncProModeStateSoon: () => void
  handleToggleProMode: () => void
}

/**
 * 集中管理 App 壳层对 window 的 legacy 桥接，避免 App.vue 散落赋值。
 */
export function useAppShellBridge(router: Router, proMode: ProModeController) {
  let onToggleProModeEvent: (() => void) | null = null
  let switchViewEvent: ((event: Event) => void) | null = null
  let sandboxMessageHandler: ((e: MessageEvent) => void) | null = null

  function installProModeBridge() {
    ;(window as Window & { setProModeEnabled?: (enabled: boolean) => void }).setProModeEnabled = (
      enabled
    ) => {
      if (!isClientModeTiersUiEnabled()) {
        if (enabled) return
        proMode.isProMode.value = false
        void proMode.exitModProMode()
        return
      }
      const shouldEnable = !!enabled
      const active = proMode.isProMode.value || proMode.readProModeStateFromDom()
      if (shouldEnable === active) {
        proMode.isProMode.value = active
        return
      }
      if (!proMode.resolveModProEntryPath() && proMode.hasLegacyProModeRuntime()) {
        const legacyToggle =
          (window as Window & { __legacyToggleProMode?: () => void; toggleProMode?: () => void })
            .__legacyToggleProMode ||
          (window as Window & { toggleProMode?: () => void }).toggleProMode
        legacyToggle?.()
        proMode.syncProModeStateSoon()
      } else if (shouldEnable) {
        void proMode.enterModProMode()
      } else {
        void proMode.exitModProMode()
      }
    }

    onToggleProModeEvent = () => {
      if (!isClientModeTiersUiEnabled()) return
      proMode.handleToggleProMode()
    }
    window.addEventListener('xcagi:toggle-pro-mode', onToggleProModeEvent)
  }

  function installSwitchViewBridge() {
    switchViewEvent = (event: Event) => {
      const view = (event as CustomEvent<{ view?: string }>).detail?.view
      if (view) {
        console.log('[AppShellBridge] xcagi:switch-view received, navigating to:', view)
        router.push({ name: view })
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
    if (onToggleProModeEvent) {
      window.removeEventListener('xcagi:toggle-pro-mode', onToggleProModeEvent)
      onToggleProModeEvent = null
    }
    if (switchViewEvent) {
      window.removeEventListener('xcagi:switch-view', switchViewEvent)
      switchViewEvent = null
    }
    if (sandboxMessageHandler) {
      window.removeEventListener('message', sandboxMessageHandler)
      sandboxMessageHandler = null
    }
    const w = window as Window & {
      setProModeEnabled?: (enabled: boolean) => void
      __XCAGI_IS_PRO_MODE?: boolean
    }
    Reflect.deleteProperty(w, 'setProModeEnabled')
    Reflect.deleteProperty(w, '__XCAGI_IS_PRO_MODE')
  }

  return {
    installProModeBridge,
    installSwitchViewBridge,
    installSandboxBridge,
    bindLegacyUploadHooks,
    uninstall,
  }
}

import type { Router } from 'vue-router'
import { navigateFromSidebarKey } from '@/utils/sidebarNavigation'

interface DesktopDeepLink {
  raw: string
  host: string
  params: Record<string, string>
}

interface DesktopShellApi {
  onDeepLink?: (callback: (url: string) => void) => () => void
  consumeDeepLink?: () => Promise<string | null>
  onVoiceInvoke?: (callback: () => void) => () => void
}

/** 解析 xcagi:// 深链为结构化对象，失败返回 null。 */
export function parseDesktopDeepLinkv2(rawUrl: string): DesktopDeepLink | null {
  if (!rawUrl || !rawUrl.startsWith('xcagi://')) return null
  try {
    const url = new URL(rawUrl)
    const params: Record<string, string> = {}
    url.searchParams.forEach((value, key) => {
      params[key] = value
    })
    return { raw: rawUrl, host: url.hostname.toLowerCase(), params }
  } catch {
    return null
  }
}

/** 由深链决定跳转目标；host 为空/chat/home 默认进对话页，未知 host 回退对话页。 */
export function navigateByDeepLink(router: Router, deepLink: DesktopDeepLink): void {
  const host = deepLink.host
  const isChatIntent = !host || host === 'chat' || host === 'home' || host === 'message'

  if (isChatIntent) {
    void navigateFromSidebarKey(router, 'chat')
    if (deepLink.params.q) {
      const input = document.getElementById('messageInput') as HTMLTextAreaElement | null
      if (input) {
        input.value = String(deepLink.params.q).slice(0, 500)
        input.focus()
        input.dispatchEvent(new Event('input', { bubbles: true }))
      }
    }
    return
  }
  void navigateFromSidebarKey(router, host).then((applied) => {
    if (!applied) void navigateFromSidebarKey(router, 'chat')
  })
}

/**
 * 集中管理 App 壳层对 window 的 legacy 桥接，避免 App.vue 散落赋值。
 */
export function useAppShellBridge(router: Router) {
  let switchViewEvent: ((event: Event) => void) | null = null
  let sandboxMessageHandler: ((e: MessageEvent) => void) | null = null
  let unlistenDeepLink: (() => void) | null = null
  let unlistenVoiceInvoke: (() => void) | null = null

  /** 深链（xcagi://）：消费启动前的 pending 唤起 + 监听实时唤起，统一路由导航。 */
  function installDesktopShellIntegrations() {
    const shell = (window as Window & { xcagiDesktop?: DesktopShellApi }).xcagiDesktop
    if (!shell) return
    try {
      unlistenDeepLink = shell.onDeepLink?.((rawUrl) => {
        const parsed = parseDesktopDeepLinkv2(rawUrl)
        if (parsed) navigateByDeepLink(router, parsed)
      }) ?? null
      if (shell.consumeDeepLink) {
        void shell.consumeDeepLink().then((pending) => {
          if (typeof pending === 'string') {
            const parsed = parseDesktopDeepLinkv2(pending)
            if (parsed) navigateByDeepLink(router, parsed)
          }
        })
      }
    } catch (e) {
      console.warn('[AppShellBridge] deep link install failed:', e)
    }

    // 语音唤起：确保在对话页并聚焦输入框。
    try {
      unlistenVoiceInvoke =
        shell.onVoiceInvoke?.(() => {
          void navigateFromSidebarKey(router, 'chat')
          window.setTimeout(() => {
            const input = document.getElementById('messageInput') as HTMLTextAreaElement | null
            input?.focus()
          }, 0)
        }) ?? null
    } catch (e) {
      console.warn('[AppShellBridge] voice invoke install failed:', e)
    }
  }

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
    try {
      unlistenDeepLink?.()
      unlistenDeepLink = null
      unlistenVoiceInvoke?.()
      unlistenVoiceInvoke = null
    } catch {
      /* ignore */
    }
  }

  return {
    installDesktopShellIntegrations,
    installSwitchViewBridge,
    installSandboxBridge,
    bindLegacyUploadHooks,
    uninstall,
  }
}

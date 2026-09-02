// 拆分自 App.vue：侧栏/工作台动作（切换模式、新对话、会话选择、设置、登出等，逻辑逐字迁移，行为不变）。
import { nextTick } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import type { Router } from 'vue-router'
import { disconnectRealtime } from '../realtimeClient'
import { requestMicInUserGesture } from '../composables/asr/micPreflight'
import { confirmDanger } from '../composables/useDangerConfirm'
import { useAuthStore } from '../stores/auth'
import { useNotificationStore } from '../stores/notifications'
import { useWalletStore } from '../stores/wallet'
import type { useWorkbenchSidebarStore } from '../stores/workbenchSidebar'

export interface ShellActionDeps {
  router: Router
  wbSidebar: ReturnType<typeof useWorkbenchSidebarStore>
  isWorkbenchHome: ComputedRef<boolean>
  convSwipeOffset: Record<string, number>
  convJustSwiped: Ref<boolean>
  currentMode: Ref<'client' | 'admin'>
  enterAdminRoute: (routeName: string) => void
}

export function useShellActions(deps: ShellActionDeps) {
  const { router, wbSidebar, isWorkbenchHome, convSwipeOffset, convJustSwiped, currentMode, enterAdminRoute } = deps
  const authStore = useAuthStore()
  const walletStore = useWalletStore()
  const notificationStore = useNotificationStore()

  function switchMode(mode: 'client' | 'admin') {
    if (mode === 'admin') {
      enterAdminRoute('admin-database')
      return
    }
    currentMode.value = 'client'
    void router.push({ name: 'workbench-home' })
  }

  function handleSidebarSettings() {
    const open = () => window.dispatchEvent(new CustomEvent('wb-open-settings'))
    if (!isWorkbenchHome.value) {
      router.push({ name: 'workbench-home' }).then(() => nextTick(open))
      return
    }
    open()
  }

  function handleNewChat() {
    if (!isWorkbenchHome.value) {
      router.push({ name: 'workbench-home' })
    }
    window.dispatchEvent(new CustomEvent('wb-new-chat'))
  }

  function handlePickConversation(id: string) {
    if (convJustSwiped.value) {
      convJustSwiped.value = false
      return
    }
    if (convSwipeOffset[id]) {
      convSwipeOffset[id] = 0
      return
    }
    Object.keys(convSwipeOffset).forEach((k) => {
      if (k !== id && convSwipeOffset[k]) convSwipeOffset[k] = 0
    })
    wbSidebar.pickConversation(id)
    wbSidebar.closeMobile()
    try {
      window.dispatchEvent(new CustomEvent('wb-pick-conversation', { detail: { id } }))
    } catch {
      /* ignore */
    }
    if (!isWorkbenchHome.value) {
      router.push({ name: 'workbench-home' })
    }
  }

  function emitWorkbenchModeSwitch(mode: 'direct' | 'make' | 'voice') {
    try {
      window.dispatchEvent(new CustomEvent('wb-mode-switch', { detail: mode }))
    } catch {
      try {
        const ev = document.createEvent('CustomEvent')
        ev.initCustomEvent('wb-mode-switch', true, true, mode)
        window.dispatchEvent(ev)
      } catch {
        /* activeMode 已经同步；事件只用于工作台内的过渡和附加动作 */
      }
    }
  }

  function handleModeClick(mode: 'direct' | 'make' | 'voice') {
    wbSidebar.closeMobile()
    if (mode === 'voice') {
      requestMicInUserGesture()
    }
    wbSidebar.setActiveMode(mode)
    if (!isWorkbenchHome.value) {
      router.push({ name: 'workbench-home' })
    } else {
      emitWorkbenchModeSwitch(mode)
    }
  }

  async function confirmRemoveConversation(id: string) {
    const conv = wbSidebar.conversations.find((c) => c.id === id)
    const title = conv?.title?.trim() || '新对话'
    const ok = await confirmDanger({
      title: '删除对话',
      message: `确定删除「${title}」？此操作不可恢复。`,
      confirmLabel: '删除',
      destructive: true,
    })
    if (ok) wbSidebar.removeConversation(id)
  }

  async function doLogout() {
    const ok = await confirmDanger({
      title: '退出登录',
      message: '确定要退出当前账号吗？',
      confirmLabel: '退出',
      destructive: true,
    })
    if (!ok) return
    disconnectRealtime(true)
    authStore.logout()
    walletStore.clear()
    notificationStore.clear()
    await router.push({ name: 'login' })
  }

  return {
    switchMode,
    handleSidebarSettings,
    handleNewChat,
    handlePickConversation,
    emitWorkbenchModeSwitch,
    handleModeClick,
    confirmRemoveConversation,
    doLogout,
  }
}

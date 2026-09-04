import { onMounted, onBeforeUnmount, type Ref } from 'vue'
import type { useModsStore } from '@/stores/mods'
import { asRecord } from '@/utils/typeGuards'
import { consumeFirstAiTaskPrompt } from '@/constants/productFlow'

const CHAT_RIGHT_PANE_MQ = '(max-width: 1023px)'
const AUTO_REFRESH_STARRED_WECHAT_KEY = 'xcagi_auto_refresh_starred_wechat'

export interface UseChatViewHostDeps {
  modsStore: ReturnType<typeof useModsStore>
  modsFromStore: Ref<{ id: string; name?: string; description?: string }[]>
  autoRefreshStarredWechat: Ref<boolean>
  isTaskPaneResizable: Ref<boolean>
  messageInput: Ref<string>
  latestAssistantPush: Ref<{ title: string; description: string } | null>
  syncSessionMessages: () => Promise<void>
  chatHandleAutoAction: (action: Record<string, unknown>, userMessage?: string) => void
  sendMessage: () => Promise<void>
  batchCalculateHeights: () => void
  stopMessageTts: () => void
  cleanupVoiceInput: () => void
  stopTaskPaneResize: () => void
}

export function useChatViewHost(deps: UseChatViewHostDeps) {
  const {
    modsStore,
    modsFromStore,
    autoRefreshStarredWechat,
    isTaskPaneResizable,
    messageInput,
    latestAssistantPush,
    syncSessionMessages,
    chatHandleAutoAction,
    sendMessage,
    batchCalculateHeights,
    stopMessageTts,
    cleanupVoiceInput,
    stopTaskPaneResize,
  } = deps

  let legacyAutoActionHandler: ((action: unknown, userMessage?: string) => void) | null = null
  let onAssistantPush: ((evt: Event) => void) | null = null
  let taskPaneViewportMedia: MediaQueryList | null = null

  const persistAutoRefreshWechatSetting = () => {
    const enabled = !!autoRefreshStarredWechat.value
    localStorage.setItem(AUTO_REFRESH_STARRED_WECHAT_KEY, enabled ? '1' : '0')
    window.dispatchEvent(new CustomEvent('xcagi:auto-refresh-wechat-changed', { detail: { enabled } }))
  }

  const onAutoRefreshToolbarChange = (enabled: boolean) => {
    autoRefreshStarredWechat.value = enabled
    persistAutoRefreshWechatSetting()
  }

  const onTaskPaneViewportChange = (event: MediaQueryList | MediaQueryListEvent) => {
    isTaskPaneResizable.value = !event.matches
    if (!isTaskPaneResizable.value) stopTaskPaneResize()
  }

  onMounted(() => {
    void (async () => {
      await modsStore.initialize()
      if (!modsStore.isLoaded || modsFromStore.value.length === 0) {
        await modsStore.initialize()
      }
    })()
    void syncSessionMessages().catch(() => {})
    setTimeout(() => batchCalculateHeights(), 100)

    legacyAutoActionHandler =
      typeof (window as unknown as { handleAutoAction?: unknown }).handleAutoAction === 'function'
        ? ((window as Window & { handleAutoAction?: (a: unknown, m?: string) => void }).handleAutoAction ?? null)
        : null
    ;(window as unknown as { __VUE_CHAT_SEND__?: (m: string) => Promise<boolean> }).__VUE_CHAT_SEND__ = async (message: string) => {
      const text = String(message || '').trim()
      if (!text) return false
      messageInput.value = text
      await sendMessage()
      return true
    }
    ;(window as unknown as { __VUE_CHAT_FILL__?: (m: string) => boolean }).__VUE_CHAT_FILL__ = (message: string) => {
      const text = String(message || '').trim()
      if (!text) return false
      messageInput.value = text
      const domInput = document.getElementById('messageInput') as HTMLTextAreaElement | null
      if (domInput) domInput.value = text
      return true
    }
    const firstTaskPrompt = consumeFirstAiTaskPrompt()
    if (firstTaskPrompt) {
      messageInput.value = firstTaskPrompt
      void sendMessage()
    }
    ;(window as unknown as { __VUE_HANDLE_AUTO_ACTION__?: boolean }).__VUE_HANDLE_AUTO_ACTION__ = true
    ;(window as Window & { handleAutoAction: (a: unknown, m?: string) => void }).handleAutoAction = (
      action: unknown,
      userMessage?: string,
    ) => chatHandleAutoAction(asRecord(action), userMessage)

    onAssistantPush = (evt: Event) => {
      const detail = (evt as CustomEvent).detail
      if (!detail) return
      latestAssistantPush.value = detail
    }
    window.addEventListener('xcagi:assistant-push', onAssistantPush)
    taskPaneViewportMedia = typeof window.matchMedia === 'function' ? window.matchMedia(CHAT_RIGHT_PANE_MQ) : null
    if (taskPaneViewportMedia) {
      onTaskPaneViewportChange(taskPaneViewportMedia)
    } else {
      isTaskPaneResizable.value = true
    }
    if (typeof taskPaneViewportMedia?.addEventListener === 'function') {
      taskPaneViewportMedia.addEventListener('change', onTaskPaneViewportChange)
    } else if (typeof taskPaneViewportMedia?.addListener === 'function') {
      taskPaneViewportMedia.addListener(onTaskPaneViewportChange)
    }
  })

  onBeforeUnmount(() => {
    const w = window as unknown as Record<string, unknown>
    if (w.__VUE_CHAT_SEND__) delete w.__VUE_CHAT_SEND__
    if (w.__VUE_CHAT_FILL__) delete w.__VUE_CHAT_FILL__
    w.__VUE_HANDLE_AUTO_ACTION__ = false
    if (legacyAutoActionHandler) {
      ;(window as unknown as { handleAutoAction: typeof legacyAutoActionHandler }).handleAutoAction = legacyAutoActionHandler
    }
    if (onAssistantPush) {
      window.removeEventListener('xcagi:assistant-push', onAssistantPush)
      onAssistantPush = null
    }
    stopTaskPaneResize()
    if (taskPaneViewportMedia) {
      if (typeof taskPaneViewportMedia.removeEventListener === 'function') {
        taskPaneViewportMedia.removeEventListener('change', onTaskPaneViewportChange)
      } else if (typeof taskPaneViewportMedia.removeListener === 'function') {
        taskPaneViewportMedia.removeListener(onTaskPaneViewportChange)
      }
    }
    stopMessageTts()
    cleanupVoiceInput()
  })

  return {
    onAutoRefreshToolbarChange,
  }
}

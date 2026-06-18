import { onMounted, onBeforeUnmount, watch, type Ref } from 'vue'
import type { Router } from 'vue-router'
import type { ShipmentTask } from '@/composables/useShipmentTask'
import {
  resetClientModeTierLocalState,
  PRO_INTENT_EXPERIENCE_KEY,
} from '@/constants/clientModeTiers'
import { resolveHostBusinessPageRedirect } from '@/utils/hostBusinessPageRedirect'
import { asRecord } from '@/utils/typeGuards'
import type { useModsStore } from '@/stores/mods'

const CHAT_RIGHT_PANE_MQ = '(max-width: 1023px)'
const AUTO_REFRESH_STARRED_WECHAT_KEY = 'xcagi_auto_refresh_starred_wechat'

export interface UseChatViewHostDeps {
  router: Router
  modsStore: ReturnType<typeof useModsStore>
  modsFromStore: Ref<{ id: string; name?: string; description?: string }[]>
  clientModeTiersUiEnabled: boolean
  proIntentExperienceEnabled: Ref<boolean>
  autoRefreshStarredWechat: Ref<boolean>
  isTaskPaneResizable: Ref<boolean>
  messageInput: Ref<string>
  isProMode: Ref<boolean>
  currentTask: Ref<ShipmentTask | null>
  proRuntimeTask: Ref<{
    title: string
    statusText: string
    statusClass: string
    description: string
  } | null>
  latestAssistantPush: Ref<{ title: string; description: string } | null>
  syncProModeState: () => void
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
    router,
    modsStore,
    modsFromStore,
    clientModeTiersUiEnabled,
    proIntentExperienceEnabled,
    autoRefreshStarredWechat,
    isTaskPaneResizable,
    messageInput,
    isProMode,
    currentTask,
    proRuntimeTask,
    latestAssistantPush,
    syncProModeState,
    syncSessionMessages,
    chatHandleAutoAction,
    sendMessage,
    batchCalculateHeights,
    stopMessageTts,
    cleanupVoiceInput,
    stopTaskPaneResize,
  } = deps

  let legacyAutoActionHandler: ((action: unknown, userMessage?: string) => void) | null = null
  let proRuntimeClearTimer: number | null = null
  let switchViewHandler: ((evt: Event) => void) | null = null
  let proModeObserver: MutationObserver | null = null
  let onProModeChanged: ((evt: Event) => void) | null = null
  let onAssistantPush: ((evt: Event) => void) | null = null
  let taskPaneViewportMedia: MediaQueryList | null = null

  const persistAutoRefreshWechatSetting = () => {
    const enabled = !!autoRefreshStarredWechat.value
    localStorage.setItem(AUTO_REFRESH_STARRED_WECHAT_KEY, enabled ? '1' : '0')
    window.dispatchEvent(
      new CustomEvent('xcagi:auto-refresh-wechat-changed', { detail: { enabled } }),
    )
  }

  const persistProIntentExperienceSetting = () => {
    if (!clientModeTiersUiEnabled) {
      proIntentExperienceEnabled.value = false
      resetClientModeTierLocalState()
      return
    }
    const enabled = !!proIntentExperienceEnabled.value
    localStorage.setItem(PRO_INTENT_EXPERIENCE_KEY, enabled ? '1' : '0')
    window.dispatchEvent(
      new CustomEvent('xcagi:pro-intent-experience-changed', { detail: { enabled } }),
    )
  }

  const syncProIntentExperienceFromStorage = () => {
    proIntentExperienceEnabled.value = localStorage.getItem(PRO_INTENT_EXPERIENCE_KEY) === '1'
  }

  const onProIntentToolbarChange = (enabled: boolean) => {
    proIntentExperienceEnabled.value = enabled
    persistProIntentExperienceSetting()
  }

  const onAutoRefreshToolbarChange = (enabled: boolean) => {
    autoRefreshStarredWechat.value = enabled
    persistAutoRefreshWechatSetting()
  }

  const onTaskPaneViewportChange = (event: MediaQueryList | MediaQueryListEvent) => {
    isTaskPaneResizable.value = !event.matches
    if (!isTaskPaneResizable.value) stopTaskPaneResize()
  }

  const onStorageForProIntent = (e: StorageEvent) => {
    if (e.key != null && e.key !== PRO_INTENT_EXPERIENCE_KEY) return
    syncProIntentExperienceFromStorage()
  }

  function mapProRuntimeStatus(status: string) {
    const s = String(status || '').toLowerCase()
    if (s === 'running' || s === 'in-progress' || s === 'dispatch' || s === 'matched') {
      return { statusText: '进行中', statusClass: 'in-progress' }
    }
    if (s === 'done' || s === 'completed' || s === 'complete') {
      return { statusText: '已完成', statusClass: 'completed' }
    }
    if (s === 'failed' || s === 'failure') return { statusText: '失败', statusClass: 'completed' }
    if (s === 'error' || s === 'exception') return { statusText: '异常', statusClass: 'completed' }
    if (s === 'idle' || s === '') return { statusText: '', statusClass: '' }
    return { statusText: s || '进行中', statusClass: 'in-progress' }
  }

  function clearProRuntimeTimer() {
    if (proRuntimeClearTimer) {
      clearTimeout(proRuntimeClearTimer)
      proRuntimeClearTimer = null
    }
  }

  let lastProRuntimeUpdatedAt: string | null = null

  function setProRuntimeTaskFromEvent(evt: Event) {
    if (currentTask.value) return
    const payload = (evt as CustomEvent).detail ?? {}
    const statusRaw = payload.status
    const s = String(statusRaw || '').toLowerCase()
    if (s === 'idle' || s === '') {
      clearProRuntimeTimer()
      lastProRuntimeUpdatedAt = null
      proRuntimeTask.value = null
      return
    }
    clearProRuntimeTimer()
    const { statusText, statusClass } = mapProRuntimeStatus(statusRaw)
    const title = String(payload.current_task || '').trim() || '工具执行'
    const toolName = String(payload.current_tool || '').trim()
    const updatedAt = payload.updated_at || ''
    lastProRuntimeUpdatedAt = updatedAt || lastProRuntimeUpdatedAt
    const timeText = updatedAt
      ? new Date(updatedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      : ''
    proRuntimeTask.value = {
      title,
      statusText,
      statusClass,
      description: [toolName ? `工具：${toolName}` : '', timeText ? `更新时间：${timeText}` : '']
        .filter(Boolean)
        .join('；'),
    }
    if (['done', 'completed', 'failed', 'error', 'exception'].includes(s)) {
      proRuntimeClearTimer = window.setTimeout(() => {
        if (currentTask.value) return
        if (!lastProRuntimeUpdatedAt || lastProRuntimeUpdatedAt === updatedAt) {
          proRuntimeTask.value = null
        }
        proRuntimeClearTimer = null
      }, 4500)
    }
  }

  watch(currentTask, (task) => {
    if (!task || task?.type !== 'shipment_generate' || task?.completed) return
    if (String(task?.customOrderNumber || '').trim()) return
  })

  onMounted(() => {
    if (!clientModeTiersUiEnabled) {
      resetClientModeTierLocalState()
      proIntentExperienceEnabled.value = false
    }
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
        ? (window as Window & { handleAutoAction?: (a: unknown, m?: string) => void }).handleAutoAction ?? null
        : null
    ;(window as unknown as { __VUE_CHAT_SEND__?: (m: string) => Promise<boolean> }).__VUE_CHAT_SEND__ =
      async (message: string) => {
        const text = String(message || '').trim()
        if (!text) return false
        messageInput.value = text
        await sendMessage()
        return true
      }
    ;(window as unknown as { __VUE_CHAT_FILL__?: (m: string) => boolean }).__VUE_CHAT_FILL__ = (
      message: string,
    ) => {
      const text = String(message || '').trim()
      if (!text) return false
      messageInput.value = text
      const domInput = document.getElementById('messageInput') as HTMLTextAreaElement | null
      if (domInput) domInput.value = text
      return true
    }
    ;(window as unknown as { __VUE_HANDLE_AUTO_ACTION__?: boolean }).__VUE_HANDLE_AUTO_ACTION__ = true
    ;(window as Window & { handleAutoAction: (a: unknown, m?: string) => void }).handleAutoAction = (
      action: unknown,
      userMessage?: string,
    ) => chatHandleAutoAction(asRecord(action), userMessage)
    syncProModeState()
    window.addEventListener('xcagi:pro-task-status', setProRuntimeTaskFromEvent)

    switchViewHandler = (evt: Event) => {
      const targetView = (evt as CustomEvent).detail?.view
      if (targetView && typeof targetView === 'string') {
        const modPath = resolveHostBusinessPageRedirect(targetView)
        if (modPath) router.push(modPath)
        else router.push({ name: targetView })
      }
    }
    window.addEventListener('xcagi:switch-view', switchViewHandler)
    onProModeChanged = (evt: Event) => {
      isProMode.value = !!(evt as CustomEvent).detail?.isProMode
    }
    window.addEventListener('xcagi:pro-mode-changed', onProModeChanged)
    onAssistantPush = (evt: Event) => {
      const detail = (evt as CustomEvent).detail
      if (!detail) return
      latestAssistantPush.value = detail
    }
    window.addEventListener('xcagi:assistant-push', onAssistantPush)
    window.addEventListener('xcagi:pro-intent-experience-changed', syncProIntentExperienceFromStorage)
    window.addEventListener('storage', onStorageForProIntent)
    taskPaneViewportMedia =
      typeof window.matchMedia === 'function' ? window.matchMedia(CHAT_RIGHT_PANE_MQ) : null
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
    if (typeof MutationObserver === 'function') {
      const observer = new MutationObserver(() => syncProModeState())
      if (typeof observer.observe !== 'function') return
      proModeObserver = observer
      observer.observe(document.body, { attributes: true, attributeFilter: ['class'] })
      const overlay = document.getElementById('proModeOverlay')
      if (overlay) {
        observer.observe(overlay, { attributes: true, attributeFilter: ['class', 'style'] })
      }
    }
  })

  onBeforeUnmount(() => {
    const w = window as unknown as Record<string, unknown>
    if (w.__VUE_CHAT_SEND__) delete w.__VUE_CHAT_SEND__
    if (w.__VUE_CHAT_FILL__) delete w.__VUE_CHAT_FILL__
    w.__VUE_HANDLE_AUTO_ACTION__ = false
    if (legacyAutoActionHandler) {
      ;(window as unknown as { handleAutoAction: typeof legacyAutoActionHandler }).handleAutoAction =
        legacyAutoActionHandler
    }
    window.removeEventListener('xcagi:pro-task-status', setProRuntimeTaskFromEvent)
    if (switchViewHandler) window.removeEventListener('xcagi:switch-view', switchViewHandler)
    if (onProModeChanged) {
      window.removeEventListener('xcagi:pro-mode-changed', onProModeChanged)
      onProModeChanged = null
    }
    if (onAssistantPush) {
      window.removeEventListener('xcagi:assistant-push', onAssistantPush)
      onAssistantPush = null
    }
    window.removeEventListener('xcagi:pro-intent-experience-changed', syncProIntentExperienceFromStorage)
    window.removeEventListener('storage', onStorageForProIntent)
    if (proModeObserver) {
      proModeObserver.disconnect()
      proModeObserver = null
    }
    stopTaskPaneResize()
    if (taskPaneViewportMedia) {
      if (typeof taskPaneViewportMedia.removeEventListener === 'function') {
        taskPaneViewportMedia.removeEventListener('change', onTaskPaneViewportChange)
      } else if (typeof taskPaneViewportMedia.removeListener === 'function') {
        taskPaneViewportMedia.removeListener(onTaskPaneViewportChange)
      }
    }
    clearProRuntimeTimer()
    stopMessageTts()
    cleanupVoiceInput()
  })

  return {
    onProIntentToolbarChange,
    onAutoRefreshToolbarChange,
  }
}

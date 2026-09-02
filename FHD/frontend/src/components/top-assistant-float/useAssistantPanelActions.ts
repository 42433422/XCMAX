import { nextTick } from 'vue'
import type { useTutorialStore } from '@/stores/tutorial'
import type { AssistantFloatState } from './useAssistantFloatState'

const FLOAT_TAB_ORDER = ['push', 'assistant', 'starterPack', 'tutorial']
const FLOAT_TAB_DATA_ID: Record<string, string> = {
  push: 'tab-push',
  assistant: 'tab-assistant',
  starterPack: 'tab-starterPack',
  tutorial: 'tab-tutorial',
}
const MAX_PUSH_ITEMS = 12
const MAX_OPERATION_LOG = 30

type TutorialStore = ReturnType<typeof useTutorialStore>

/**
 * 面板开关 / 标签页 / 推送弹窗 / 操作日志（由 TopAssistantFloat.vue 机械切出，行为不变）。
 */
export function useAssistantPanelActions(
  state: AssistantFloatState,
  { tutorialStore }: { tutorialStore: TutorialStore },
) {
  const {
    isOpen,
    activeTab,
    floatToggleRef,
    assistantPanelRef,
    pushFeed,
    popupNotice,
    hasUnreadPush,
    operationHistory,
  } = state

  let noticeTimer: ReturnType<typeof setTimeout> | null = null

  const focusToggleAfterClose = () => {
    nextTick(() => {
      floatToggleRef.value?.focus?.()
    })
  }

  /** 关闭 Teleport 副窗并将焦点回到顶栏触发按钮（教程锁定副窗时不强制关） */
  const closeAssistantPanelUi = () => {
    if (tutorialStore.isActive && tutorialStore.currentStep?.assistantTab) {
      return
    }
    isOpen.value = false
    focusToggleAfterClose()
  }

  const onDocumentKeydownCapture = (e: KeyboardEvent) => {
    if (e.key !== 'Escape' || !isOpen.value) return
    if (tutorialStore.isActive && tutorialStore.currentStep?.assistantTab) return
    e.preventDefault()
    e.stopPropagation()
    isOpen.value = false
    focusToggleAfterClose()
  }

  const recordOperation = (type: string, detail: Record<string, unknown> | null = {}) => {
    operationHistory.value = [
      {
        id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        type: String(type || ''),
        detail: detail || {},
        at: Date.now(),
      },
      ...operationHistory.value,
    ].slice(0, MAX_OPERATION_LOG)
  }

  const toggleOpen = async () => {
    recordOperation('toggle_float', { open: !isOpen.value })
    const next = !isOpen.value
    isOpen.value = next
    if (next) {
      hasUnreadPush.value = false
      popupNotice.value = null
      if (noticeTimer) {
        clearTimeout(noticeTimer)
        noticeTimer = null
      }
      await nextTick()
      assistantPanelRef.value?.querySelector<HTMLElement>('.assistant-close')?.focus()
    } else {
      focusToggleAfterClose()
    }
  }

  const openTutorialTab = () => {
    recordOperation('open_tutorial_tab', {})
    isOpen.value = true
    hasUnreadPush.value = false
    popupNotice.value = null
    activeTab.value = 'tutorial'
  }

  const onAssistantPanelKeydown = (e: KeyboardEvent) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    const t = e.target
    if (!(t instanceof HTMLElement) || t.getAttribute('role') !== 'tab') return
    e.preventDefault()
    const cur = FLOAT_TAB_ORDER.indexOf(activeTab.value)
    if (cur < 0) return
    const dir = e.key === 'ArrowRight' ? 1 : -1
    const nextI = (cur + dir + FLOAT_TAB_ORDER.length) % FLOAT_TAB_ORDER.length
    const nextTab = FLOAT_TAB_ORDER[nextI]
    if (nextTab === 'tutorial') {
      openTutorialTab()
    } else {
      activeTab.value = nextTab
    }
    nextTick(() => {
      const tid = FLOAT_TAB_DATA_ID[nextTab]
      assistantPanelRef.value?.querySelector<HTMLElement>(`[data-tutorial-id="${tid}"]`)?.focus()
    })
  }

  const addPush = (detail: { title?: string; description?: string } | null | undefined) => {
    const title = (detail?.title || '').trim() || '新推送'
    const description = (detail?.description || '').trim() || '收到一条助手消息'
    recordOperation('assistant_push', { title, description })
    pushFeed.value = [
      {
        id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        title,
        description,
      },
      ...pushFeed.value,
    ].slice(0, MAX_PUSH_ITEMS)

    if (!isOpen.value) {
      hasUnreadPush.value = true
      popupNotice.value = {
        title,
        description,
      }
      if (noticeTimer) clearTimeout(noticeTimer)
      noticeTimer = setTimeout(() => {
        popupNotice.value = null
        noticeTimer = null
      }, 6000)
    }
  }

  const openFromNotice = () => {
    isOpen.value = true
    hasUnreadPush.value = false
    popupNotice.value = null
    if (noticeTimer) {
      clearTimeout(noticeTimer)
      noticeTimer = null
    }
  }

  /** 供卸载钩子清理弹窗定时器 */
  const clearNoticeTimer = () => {
    if (noticeTimer) {
      clearTimeout(noticeTimer)
      noticeTimer = null
    }
  }

  return {
    FLOAT_TAB_ORDER,
    FLOAT_TAB_DATA_ID,
    MAX_PUSH_ITEMS,
    MAX_OPERATION_LOG,
    focusToggleAfterClose,
    closeAssistantPanelUi,
    onDocumentKeydownCapture,
    recordOperation,
    toggleOpen,
    openTutorialTab,
    onAssistantPanelKeydown,
    addPush,
    openFromNotice,
    clearNoticeTimer,
  }
}

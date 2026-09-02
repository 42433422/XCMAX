import { nextTick } from 'vue'
import api from '@/api'
import type { Router } from 'vue-router'
import type { useTutorialStore } from '@/stores/tutorial'
import type { useTutorialCatalog } from '@/composables/useTutorialCatalog'
import { DEFAULT_TUTORIAL_TRACK_ID } from '@/constants/productFlow'
import type { AssistantFloatState } from './useAssistantFloatState'

type TutorialStore = ReturnType<typeof useTutorialStore>
type TutorialBuildContextGetter = ReturnType<typeof useTutorialCatalog>['buildContext']

type RecordOperationFn = (type: string, detail?: Record<string, unknown> | null) => void

/**
 * 教程启动 / 宿主入门引导（由 TopAssistantFloat.vue 机械切出，行为不变）。
 * 启动前对副窗全量状态做快照，随教程 returnContext 保存以便恢复。
 */
export function useAssistantTutorialLaunch(
  state: AssistantFloatState,
  {
    router,
    tutorialStore,
    tutorialBuildContext,
    recordOperation,
  }: {
    router: Router
    tutorialStore: TutorialStore
    tutorialBuildContext: TutorialBuildContextGetter
    recordOperation: RecordOperationFn
  },
) {
  const {
    isOpen,
    activeTab,
    showAdvancedCourses,
    pushFeed,
    productKeyword,
    productRows,
    linkedSheetName,
    linkedSheetIndex,
    linkedGridData,
    linkedSheetFields,
    linkedSheetSampleRows,
    topScrollInnerWidth,
    loadingProducts,
    lastProductSearchQuery,
    productSearchFailed,
    productSearchErrorText,
    lastProductSearchTotal,
    popupNotice,
    hasUnreadPush,
    operationHistory,
  } = state

  const startHostOnboardingGuide = async () => {
    recordOperation('start_host_onboarding_tutorial', {})
    const returnPath = String(router.currentRoute.value?.fullPath || '/').trim() || '/'
    isOpen.value = false
    await router.push({
      name: 'product-onboarding',
      query: {
        step: 'welcome',
        from: 'tutorial',
        redirect: returnPath,
      },
    }).catch(() => {})
  }

  const startTutorialGuide = async (track: string = DEFAULT_TUTORIAL_TRACK_ID) => {
    const t = String(track || DEFAULT_TUTORIAL_TRACK_ID).trim() || DEFAULT_TUTORIAL_TRACK_ID
    if (t === DEFAULT_TUTORIAL_TRACK_ID) {
      await startHostOnboardingGuide()
      return
    }
    if (t === 'advanced') {
      showAdvancedCourses.value = true
      activeTab.value = 'tutorial'
      return
    }
    const extractChatMessagesSnapshot = () => {
      const nodes = Array.from(document.querySelectorAll('#chatMessages .message'))
      return nodes.slice(-30).map((node) => {
        const role = node.classList.contains('ai') ? 'assistant' : (node.classList.contains('user') ? 'user' : 'unknown')
        const text = String(node.textContent || '').trim().replace(/\s+/g, ' ')
        return { role, content: text.slice(0, 500) }
      }).filter((item) => item.content)
    }
    const cacheTutorialGuidePack = async (pack: Record<string, unknown>) => {
      try {
        await api.post('/api/preferences', {
          user_id: 'default',
          key: 'tutorial_guide_pack_cache',
          value: JSON.stringify(pack),
        })
      } catch (_e) {
        // 缓存失败不影响教程主流程
      }
    }
    const previousRouteName = String(router.currentRoute.value?.name || '')
    const previousOpen = isOpen.value
    const previousTab = activeTab.value
    const snapshotState = {
      pushFeed: [...pushFeed.value],
      productKeyword: productKeyword.value,
      productRows: [...productRows.value],
      linkedSheetName: linkedSheetName.value,
      linkedSheetIndex: linkedSheetIndex.value,
      linkedGridData: linkedGridData.value,
      linkedSheetFields: [...linkedSheetFields.value],
      linkedSheetSampleRows: [...linkedSheetSampleRows.value],
      topScrollInnerWidth: topScrollInnerWidth.value,
      loadingProducts: loadingProducts.value,
      lastProductSearchQuery: lastProductSearchQuery.value,
      productSearchFailed: productSearchFailed.value,
      productSearchErrorText: productSearchErrorText.value,
      lastProductSearchTotal: lastProductSearchTotal.value,
      popupNotice: popupNotice.value,
      hasUnreadPush: hasUnreadPush.value,
      operationHistory: [...operationHistory.value],
    }
    await router.push({ name: 'chat' }).catch(() => {})
    await nextTick()
    // 教程入口等同于「新对话」初始化，避免继承旧会话上下文。
    for (let i = 0; i < 4; i += 1) {
      const newConversationBtn = document.getElementById('newConversationBtn')
      if (newConversationBtn) {
        newConversationBtn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
        break
      }
      await new Promise((resolve) => setTimeout(resolve, 80))
    }
    // 进入教程前统一回到初始教学态，避免沿用上一次副窗临时状态。
    pushFeed.value = []
    productKeyword.value = ''
    productRows.value = []
    linkedSheetName.value = ''
    linkedSheetIndex.value = 0
    linkedGridData.value = null
    linkedSheetFields.value = []
    linkedSheetSampleRows.value = []
    topScrollInnerWidth.value = 0
    productSearchFailed.value = false
    productSearchErrorText.value = ''
    lastProductSearchQuery.value = ''
    lastProductSearchTotal.value = null
    operationHistory.value = []
    isOpen.value = true
    hasUnreadPush.value = false
    popupNotice.value = null
    activeTab.value = 'tutorial'
    tutorialStore.startTutorial({
      track: t,
      buildContext: tutorialBuildContext.value,
      returnContext: {
        routeName: previousRouteName || 'chat',
        assistantOpen: previousOpen,
        assistantTab: previousTab || 'push',
        assistantState: snapshotState,
      },
    })
    // 若用户已在教程标签，startTutorial 前再触发一次预热（仅首次会真正请求）
    queueMicrotask(() => {
      window.dispatchEvent(new CustomEvent('xcagi:warmup-tutorial-tts'))
    })
    const tutorialPack = {
      version: 1,
      type: 'xcagi_tutorial_guide_pack',
      createdAt: new Date().toISOString(),
      context: {
        routeBeforeTutorial: previousRouteName || 'chat',
        assistantOpenBeforeTutorial: previousOpen,
        assistantTabBeforeTutorial: previousTab || 'push',
        chatMessages: extractChatMessagesSnapshot(),
      },
      tutorial: {
        track: tutorialStore.currentTrack ?? t,
        requestedTrack: t,
        stepCount: tutorialStore.steps.length,
        steps: tutorialStore.steps.map((step, idx) => ({
          index: idx + 1,
          id: step.id,
          title: step.title,
          description: step.description,
          actionType: step.actionType,
          targetSelector: step.targetSelector,
        })),
      },
    }
    void cacheTutorialGuidePack(tutorialPack)
  }

  return {
    startHostOnboardingGuide,
    startTutorialGuide,
  }
}

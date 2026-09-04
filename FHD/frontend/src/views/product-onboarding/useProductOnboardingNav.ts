import type { Router } from 'vue-router'
import { readProductFlowCompleted } from '@/constants/productFlow'
import { invalidateHostPackCompletionCache, markHostPackSkippedThisSession } from '@/utils/hostPackOnboardingGate'
import type { useProductFlow } from '@/composables/useProductFlow'
import type { ProductOnboardingState } from './useProductOnboardingState'

type ProductFlow = ReturnType<typeof useProductFlow>

// ProductOnboardingView 的导航与流程收尾逻辑（与拆分前逐字一致）
export function useProductOnboardingNav(state: ProductOnboardingState, options: { router: Router; flow: ProductFlow }) {
  const { fromTutorial, returnPath, baselineOk } = state
  const { router, flow } = options

  function goStep(id: string) {
    const query: Record<string, string> = { step: id }
    if (fromTutorial.value) {
      query.from = 'tutorial'
      query.redirect = returnPath.value
    }
    void router.replace({ name: 'product-onboarding', query })
  }

  function returnFromTutorial() {
    void router.replace(returnPath.value)
  }

  function openModStore() {
    if (!fromTutorial.value || !readProductFlowCompleted()) {
      flow.markProductFlowCompleted()
    }
    void router.push({
      name: 'mod-store',
      query: fromTutorial.value ? {} : { onboarding: '1' },
    })
  }

  function finishHostPackFlow() {
    invalidateHostPackCompletionCache()
    if (baselineOk.value) {
      flow.markHostPackAcknowledged()
      if (!readProductFlowCompleted()) {
        flow.markProductFlowCompleted()
      }
      if (fromTutorial.value) {
        returnFromTutorial()
        return
      }
      flow.completeFlowAndGoChat(router)
      return
    }
    markHostPackSkippedThisSession()
    if (fromTutorial.value) {
      returnFromTutorial()
      return
    }
    void router.replace({ path: '/' })
  }

  function launchFirstAiTask() {
    invalidateHostPackCompletionCache()
    flow.markHostPackAcknowledged()
    if (fromTutorial.value) {
      returnFromTutorial()
      return
    }
    void router.replace({ path: '/' })
  }

  function finishToChat() {
    finishHostPackFlow()
  }

  function skipEntireFlow() {
    if (fromTutorial.value) {
      returnFromTutorial()
      return
    }
    if (baselineOk.value) {
      flow.markProductFlowCompleted()
      flow.markHostPackAcknowledged()
    } else {
      markHostPackSkippedThisSession()
    }
    finishToChat()
  }

  return {
    goStep,
    returnFromTutorial,
    openModStore,
    finishHostPackFlow,
    launchFirstAiTask,
    finishToChat,
    skipEntireFlow,
  }
}

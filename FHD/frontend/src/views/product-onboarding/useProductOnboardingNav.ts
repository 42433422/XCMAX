import type { Router } from 'vue-router'
import { readProductFlowCompleted } from '@/constants/productFlow'
import { appAlert } from '@/utils/appDialog'
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
    if (returnPath.value !== '/') query.redirect = returnPath.value
    if (router.currentRoute.value.query.industry) query.industry = state.pickedIndustryId.value
    if (fromTutorial.value) {
      query.from = 'tutorial'
      query.redirect = returnPath.value
    }
    void router.replace({ name: 'product-onboarding', query })
  }

  function loginToContinue() {
    const query: Record<string, string> = {
      step: state.currentStep.value,
      industry: state.pickedIndustryId.value,
      redirect: returnPath.value,
    }
    if (fromTutorial.value) query.from = 'tutorial'
    const redirect = router.resolve({ name: 'product-onboarding', query }).fullPath
    // The existing login error gate also disables provisional desktop resume;
    // a stale one-shot cookie hint must not bounce this explicit login back.
    void router.push({ name: 'login', query: { redirect, error: '请先登录，登录后将返回当前设置步骤。' } })
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
    // Chat consumes the queued prompt when it mounts, including tutorial replay.
    // The root route resolves to the active host or Mod chat through its guard.
    void router.replace({ path: '/' })
  }

  async function openAttendanceWorkspace() {
    if (!router.hasRoute('attendance-industry-personnel')) {
      await appAlert('考勤工作区尚未准备好，请先安装考勤功能并重新检测。')
      goStep('host-pack')
      return
    }
    flow.markHostPackAcknowledged()
    await router.push({ name: 'attendance-industry-personnel' })
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
    loginToContinue,
    returnFromTutorial,
    openModStore,
    finishHostPackFlow,
    launchFirstAiTask,
    openAttendanceWorkspace,
    finishToChat,
    skipEntireFlow,
  }
}

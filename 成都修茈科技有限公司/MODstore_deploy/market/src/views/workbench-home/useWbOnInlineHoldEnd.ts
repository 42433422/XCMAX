import { showAppToast } from '../../composables/useAppToast'
import type { useWbRunOrchestration } from './useWbRunOrchestration'

// 拆分自 WorkbenchHomeView.vue（原行 8551–8565, 8579–8585, 11545–11556）；逐字迁移，行为不变。
export function useWbOnInlineHoldEnd(ctx: ReturnType<typeof useWbRunOrchestration>) {
  const {
    wbNav, __wbState, planSession, cancelInlineVoice, finishInlineHoldAndSend, voiceBtnLongPressCancel,
    sendPlanReply, submitDraft,
  } = ctx

async function onInlineHoldEnd(target: 'direct' | 'make', e?: PointerEvent) {
  if (!__wbState.inlineHoldActive) return
  if (e && __wbState.inlineHoldPointerId >= 0 && e.pointerId !== __wbState.inlineHoldPointerId) return
  const cancel = __wbState.inlineHoldCancelIntent
  __wbState.inlineHoldActive = false
  __wbState.inlineHoldPointerId = -1
  __wbState.inlineHoldCancelIntent = false
  __wbState.inlineHoldStartY = 0
  if (cancel) {
    cancelInlineVoice(target, { silent: true })
    showAppToast('已取消', { variant: 'info' })
    return
  }
  await finishInlineHoldAndSend(target)
}
function onDirectVoicePointerUp(e: PointerEvent) {
  if (wbNav.isMobile) {
    void onInlineHoldEnd('direct', e)
    return
  }
  voiceBtnLongPressCancel()
}
function onComposerKeydown(e: KeyboardEvent): void {
  if (e.key !== 'Enter' || e.shiftKey) return
  const ps = planSession.value
  if (ps?.phase === 'chat') {
    e.preventDefault()
    void sendPlanReply()
    return
  }
  if (ps) return
  e.preventDefault()
  void submitDraft()
}

  return {
    ...ctx, onInlineHoldEnd, onDirectVoicePointerUp, onComposerKeydown,
  }
}

export type useWbOnInlineHoldEndBinds = ReturnType<typeof useWbOnInlineHoldEnd>

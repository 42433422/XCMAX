import { watch } from 'vue'
import { loadConversations, loadActiveId, saveActiveId, mergeConversationsForPick } from '../../utils/conversationStore'
import { streamLLMChat } from '../../utils/llmStream'
import { ttsConfigFromPersonalSettings } from '../../composables/useStreamingTts'
import { appendVoiceInject, isLikelyShortProceedFragment } from '../../composables/voiceUtteranceRouter'
import { applyVoiceSessionPatch, buildPlanBriefFromVoiceMessages, sanitizeVoiceUtteranceText, isLikelyAsrEchoNoise, isPlaceholderPlanContent, type VoiceTurnClassification } from '../../composables/voiceSessionAgent'
import { showAppToast } from '../../composables/useAppToast'
import { isMicPermissionError } from '../../composables/inlineVoiceUi'
import type { useWbDrawWaveform } from './useWbDrawWaveform'
import type { PendingHandoff, WorkbenchCompletionResult, WorkbenchOrchestrationSession } from './types'
import { wbLate1 as __wbLate1 } from './wbLate1'

// 拆分自 WorkbenchHomeView.vue（原行 6434–6439, 6762–6851, 6853–6878 …）；逐字迁移，行为不变。
export function useWbHandleVoicePlanReplySmart(ctx: ReturnType<typeof useWbDrawWaveform>) {
  const {
    wbSidebar, pendingHandoff, makeCompletionResult, employeeSixDimModalOpen, finalizeLoading, orchestrationSession,
    orchestrationSessionId, __wbState, planSession, planReplyDraft, voiceChecklistPaused, composerIntent,
    directDraft, directLoading, directError, directVoiceListening, directVoiceAudioLevel, ttsAutoRead,
    makeVoiceListening, directVoiceRecognizing, makeVoiceRecognizing, conversations, activeConversationId, directMessages,
    personalSettings, streamingTts, voiceS2s, voiceUnified, voiceUseUnified, voiceUseS2S,
    voiceMessages, voiceSessionState, voiceError, voiceState, voiceReport, voiceChatPhase,
    pushInject, voiceChatBusy, VOICE_TTS_FEED_OPTS, voiceAutoSend, inlineAsr, appendVoiceUserTurn,
    voiceListening, voiceMicPausedByUser, voiceDraft, resetVoiceCaptureUi, setActiveConversation, startVoiceRecognition,
    resumeVoiceListeningAfterTurn, dispatchVoiceUtterance, dismissPlanSessionFromVoice, resumeVoiceAfterChatTurn, confirmEmployeeChecklistAndRunFromVoice, buildVoiceWorkbenchPrompt,
    textsSimilarForFinalize, modelMode, llmDdOpen, pickEmployeeKey, pickModId, gearNavUserUnlocked,
    makeComposerInput, syncManualSelectionFromPreferences, applyInlineVoiceText, stopInlineVoiceCapture, clearInlineVoicePermissionHint, setInlineVoicePermissionHint,
    buildMakeCompletionResult, scrollMakeFlowToEnd, openMakeCompletionPrimary, tryOpenEmployeeSixDimModal, resolveChatProviderModel, summarizePlanSession,
    confirmSummaryAndStartPlanning, sendPlanReply,
  } = ctx

async function onVoiceDismissPlanPanel() {
  await dismissPlanSessionFromVoice()
  if (wbSidebar.activeMode === 'voice' && !voiceMicPausedByUser.value) {
    resumeVoiceListeningAfterTurn()
  }
}
async function handleVoicePlanReplySmart(
  text: string,
  classification: VoiceTurnClassification,
  opts?: { skipUserAppend?: boolean },
) {
  const ps = planSession.value
  if (!ps) {
    await runVoiceChatTurn(text, classification.replyHint, { skipUserAppend: opts?.skipUserAppend })
    return
  }

  if (classification.action === 'dismiss_plan') {
    await dismissPlanSessionFromVoice()
    await runVoiceChatTurn(
      text,
      classification.replyHint || '用户不想继续当前规划。确认理解并询问下一步。',
      { skipUserAppend: opts?.skipUserAppend },
    )
    return
  }

  appendVoiceUserTurn(text)

  if (ps.phase === 'summary') {
    if (classification.action === 'confirm_plan' && !ps.summaryNeedsClarification) {
      await confirmSummaryAndStartPlanning()
      await speakVoiceShort('好的，已进入详细规划，你可以继续补充或直接回答我的问题。')
      resumeVoiceListeningAfterTurn()
      return
    }
    if (classification.action === 'update_plan' || classification.action === 'confirm_plan') {
      applyVoiceSessionPatch(voiceSessionState.value, classification.statePatch)
      ps.displayBrief = text
      ps.fullBrief = buildPlanBriefFromVoiceMessages(
        voiceSessionState.value,
        voiceMessages.value,
        text,
      )
      ps.loading = true
      try {
        await summarizePlanSession()
      } finally {
        if (planSession.value) planSession.value.loading = false
      }
      await speakVoiceShort(
        ps.summaryNeedsClarification
          ? '还需要再补充一些信息，请继续说明。'
          : '已更新摘要，你可以说「开始规划」或点击确认。',
      )
      resumeVoiceListeningAfterTurn()
      return
    }
    await runVoiceChatTurn(text, classification.replyHint, { skipUserAppend: true })
    resumeVoiceListeningAfterTurn()
    return
  }

  if (ps.phase === 'chat') {
    if (classification.action === 'confirm_plan') {
      planReplyDraft.value = text
      await sendPlanReply()
      resumeVoiceListeningAfterTurn()
      return
    }
    planReplyDraft.value = text
    await sendPlanReply()
    resumeVoiceListeningAfterTurn()
    return
  }

  if (ps.phase === 'checklist') {
    if (classification.action === 'confirm_plan') {
      voiceChecklistPaused.value = false
      await confirmEmployeeChecklistAndRunFromVoice()
      resumeVoiceListeningAfterTurn()
      return
    }
    if (classification.action === 'update_plan') {
      planReplyDraft.value = text
      await sendPlanReply()
      resumeVoiceListeningAfterTurn()
      return
    }
    await speakVoiceShort(
      classification.replyHint || '清单已展示；说开始可进入制作，或说明要改哪一条。',
    )
    resumeVoiceListeningAfterTurn()
    return
  }
}
async function handleVoicePlanReply(text: string) {
  const ps = planSession.value
  if (!ps) {
    await runVoiceChatTurn(text)
    return
  }
  appendVoiceUserTurn(text)
  if (ps.phase === 'summary') {
    ps.displayBrief = text
    ps.fullBrief = `${ps.fullBrief || ''}\n${text}`.trim()
    await speakVoiceShort('已更新摘要，你可以说「开始规划」或点击确认。')
    resumeVoiceListeningAfterTurn()
    return
  }
  if (ps.phase === 'chat') {
    planReplyDraft.value = text
    await sendPlanReply()
    resumeVoiceListeningAfterTurn()
    return
  }
  if (ps.phase === 'checklist') {
    await confirmEmployeeChecklistAndRunFromVoice()
    resumeVoiceListeningAfterTurn()
    return
  }
}
async function injectVoiceDuringWork(text: string) {
  const t = sanitizeVoiceUtteranceText(text)
  if (!t || isPlaceholderPlanContent(t) || isLikelyShortProceedFragment(t)) return
  const topicHint = [voiceSessionState.value.userGoal, text].join(' ')
  if (isLikelyAsrEchoNoise(t, topicHint)) return
  if (pendingHandoff.value) {
    pendingHandoff.value.description = appendVoiceInject(pendingHandoff.value.description, t)
  } else if (planSession.value) {
    planSession.value.fullBrief = appendVoiceInject(planSession.value.fullBrief, t)
    if (planSession.value.displayBrief) {
      planSession.value.displayBrief = appendVoiceInject(planSession.value.displayBrief, t)
    }
  } else if (orchestrationSessionId.value || finalizeLoading.value) {
    pushInject(t)
  }
  appendVoiceUserTurn(t)
  await runVoiceChatTurn(t, '用户正在任务执行中补充需求。用一句话确认已记录，不要展开。', {
    skipUserAppend: true,
  })
}
async function runVoiceUnifiedTurn(
  userText: string,
  systemHint?: string,
  opts?: { skipUserAppend?: boolean; turnId?: string },
) {
  if (!opts?.skipUserAppend) appendVoiceUserTurn(userText)
  const assistantIdx = voiceMessages.value.length
  voiceMessages.value = [...voiceMessages.value, { role: 'assistant', content: '' }]
  const sys = buildVoiceWorkbenchPrompt(systemHint)
  const history = voiceMessages.value
    .slice(0, -1)
    .filter((m) => m.content?.trim())
    .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
  const { provider, model } = await resolveChatProviderModel()
  const ttsCfg = ttsConfigFromPersonalSettings(personalSettings.value)
  try {
    const content = await voiceUnified.endUtterance({
      text: userText,
      turnId: opts?.turnId || `t${Date.now()}`,
      system: sys,
      messages: history,
      provider,
      model,
      voice: ttsCfg.edgeVoice,
      rate: ttsCfg.rate,
      ttsEnabled: ttsAutoRead.value,
      maxTokens: 1024,
      onTextDelta: (_d, soFar) => {
        const msgs = [...voiceMessages.value]
        if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: soFar }
        voiceMessages.value = msgs
        voiceReport.value = soFar
      },
    })
    const reply = content.trim() || '（无回复）'
    const msgs = [...voiceMessages.value]
    if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: reply }
    voiceMessages.value = msgs
    voiceReport.value = reply
  } catch (e: unknown) {
    voiceError.value = e instanceof Error ? e.message : String(e)
  } finally {
    voiceChatBusy.value = false
    voiceChatPhase.value = 'idle'
    void resumeVoiceAfterChatTurn(ttsAutoRead.value)
  }
}
async function runVoiceS2STurn(
  userText: string,
  systemHint?: string,
  opts?: { skipUserAppend?: boolean; turnId?: string },
) {
  if (__wbState.s2sProvisionalStarted && textsSimilarForFinalize(userText, voiceMessages.value.filter((m) => m.role === 'user').pop()?.content || '')) {
    return
  }
  __wbState.s2sProvisionalStarted = false
  if (!opts?.skipUserAppend) {
    appendVoiceUserTurn(userText)
  }
  const assistantIdx = voiceMessages.value.length
  voiceMessages.value = [...voiceMessages.value, { role: 'assistant', content: '' }]
  const sys = buildVoiceWorkbenchPrompt(systemHint)
  const history = voiceMessages.value
    .slice(0, -1)
    .filter((m) => m.content?.trim())
    .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
  const { provider, model } = await resolveChatProviderModel()
  const ttsCfg = ttsConfigFromPersonalSettings(personalSettings.value)
  try {
    const { content } = await voiceS2s.runTurn({
      text: userText,
      turnId: opts?.turnId,
      system: sys,
      messages: history,
      provider,
      model,
      voice: ttsCfg.edgeVoice,
      rate: ttsCfg.rate,
      ttsEnabled: ttsAutoRead.value,
      maxTokens: 1024,
      onTextDelta: (_delta, soFar) => {
        const msgs = [...voiceMessages.value]
        if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: soFar }
        voiceMessages.value = msgs
        voiceReport.value = soFar
      },
    })
    const reply = content.trim() || '（无回复）'
    const msgs = [...voiceMessages.value]
    if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: reply }
    voiceMessages.value = msgs
    voiceReport.value = reply
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    voiceError.value = msg || voiceS2s.lastError.value
  } finally {
    __wbState.s2sProvisionalStarted = false
    voiceChatBusy.value = false
    voiceChatPhase.value = 'idle'
    void resumeVoiceAfterChatTurn(ttsAutoRead.value)
  }
}
async function runVoiceChatTurn(
  userText: string,
  systemHint?: string,
  opts?: { skipUserAppend?: boolean; speculative?: boolean; fromTypedComposer?: boolean },
) {
  if (voiceChatBusy.value && !opts?.speculative && !opts?.fromTypedComposer) return
  voiceChatBusy.value = true
  voiceChatPhase.value = 'streaming'
  voiceState.value = 'processing'
  const useTts = ttsAutoRead.value
  const useS2S = voiceUseS2S.value && !opts?.speculative
  const useUnified = voiceUseUnified.value && !opts?.speculative
  try {
    if (useUnified) {
      await runVoiceUnifiedTurn(userText, systemHint, { skipUserAppend: opts?.skipUserAppend })
      return
    }
    if (useS2S) {
      await runVoiceS2STurn(userText, systemHint, { skipUserAppend: opts?.skipUserAppend })
      return
    }
    if (!opts?.skipUserAppend) {
      appendVoiceUserTurn(userText)
    }
    const assistantIdx = voiceMessages.value.length
    voiceMessages.value = [...voiceMessages.value, { role: 'assistant', content: '' }]
    const providerModelPromise = resolveChatProviderModel()
    const sys = buildVoiceWorkbenchPrompt(systemHint)
    const history = voiceMessages.value.slice(0, -1).map((m) => ({ role: m.role, content: m.content }))
    const ctx = opts?.speculative
      ? [...history, { role: 'user', content: userText }]
      : history
    if (useTts) {
      if (!opts?.speculative) streamingTts.stop()
      streamingTts.resetStream(VOICE_TTS_FEED_OPTS)
      streamingTts.warmUp()
    }
    const { provider, model } = await providerModelPromise
    __wbState.voiceStreamHandle = streamLLMChat({
      provider,
      model,
      messages: [{ role: 'system', content: sys }, ...ctx],
      maxTokens: 1024,
      onToken: (_delta, soFar) => {
        const msgs = [...voiceMessages.value]
        if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: soFar }
        voiceMessages.value = msgs
        voiceReport.value = soFar
        if (useTts) streamingTts.feed(soFar)
      },
      onError: (e) => {
        voiceError.value = e?.message || String(e)
      },
      onDone: (full, aborted) => {
        const reply = (aborted ? voiceMessages.value[assistantIdx]?.content : full) || '（无回复）'
        const msgs = [...voiceMessages.value]
        if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: reply }
        voiceMessages.value = msgs
        voiceReport.value = reply
        if (useTts && !aborted) streamingTts.finish(reply)
        else if (useTts && aborted) streamingTts.stop()
      },
    })
    await __wbState.voiceStreamHandle.done
  } catch (e: unknown) {
    voiceError.value = e instanceof Error ? e.message : String(e)
  } finally {
    __wbState.voiceStreamHandle = null
    const s2sStillActive =
      voiceUseS2S.value && (__wbState.s2sProvisionalStarted || voiceS2s.isPlaying() || voiceS2s.state.value === 'streaming')
    if (!s2sStillActive) {
      voiceChatBusy.value = false
      voiceChatPhase.value = 'idle'
      __wbState.s2sProvisionalStarted = false
      void resumeVoiceAfterChatTurn(ttsAutoRead.value)
    }
  }
}
async function speakVoiceShort(text: string) {
  if (!text.trim()) {
    resumeVoiceListeningAfterTurn()
    return
  }
  voiceState.value = 'reporting'
  voiceChatPhase.value = 'speaking'
  voiceReport.value = text
  if (ttsAutoRead.value) {
    if (voiceUseS2S.value) {
      const ttsCfg = ttsConfigFromPersonalSettings(personalSettings.value)
      const { provider, model } = await resolveChatProviderModel()
      try {
        await voiceS2s.runTurn({
          text,
          system: '请用一句话朗读以下内容，不要展开。',
          messages: [],
          provider,
          model,
          voice: ttsCfg.edgeVoice,
          rate: ttsCfg.rate,
          ttsEnabled: true,
          maxTokens: 256,
          onTextDelta: () => {},
        })
        await voiceS2s.whenAudioIdle()
      } catch {
        await streamingTts.speak(text)
      }
    } else {
      await streamingTts.speak(text)
    }
  }
  voiceChatPhase.value = 'idle'
  voiceState.value = 'idle'
  resumeVoiceListeningAfterTurn()
}
/** @deprecated use dispatchVoiceUtterance */
async function _submitVoiceTurn() {
  const content = voiceDraft.value.trim()
  if (!content) return
  await dispatchVoiceUtterance(content)
}
function _speakTextAndContinue(text: string) {
  voiceState.value = 'reporting'
  void streamingTts.speak(text).finally(() => {
    voiceState.value = 'idle'
    if (voiceAutoSend.value && !voiceMicPausedByUser.value) {
      setTimeout(() => startVoiceRecognition({ fresh: true }), 400)
    }
  })
}
watch(composerIntent, (intent) => {
  pickEmployeeKey.value = ''
  pickModId.value = ''
  voiceSessionState.value.mode =
    intent === 'employee' ? 'employee' : intent === 'mod' ? 'mod' : 'skill'
})
watch(activeConversationId, () => {
  gearNavUserUnlocked.value = false
})
watch(
  () => wbSidebar.activeConversationId,
  (id) => {
    if (!id) return
    if (id === activeConversationId.value) {
      const fresh = loadConversations().find((c) => c.id === id)
      if (directMessages.value.length === 0 && (fresh?.messages?.length ?? 0) > 0) {
        setActiveConversation(id)
      }
      return
    }
    setActiveConversation(id)
  },
)
watch(
  () => wbSidebar.conversations.map((c) => `${c.id}:${c.updatedAt}:${c.messages?.length ?? 0}`).join('|'),
  () => {
    if (__wbState.syncingConvToSidebar) return
    const loaded = loadConversations()
    const aid = wbSidebar.activeConversationId || loadActiveId() || activeConversationId.value
    if (aid) {
      conversations.value = mergeConversationsForPick(
        conversations.value,
        loaded,
        aid,
        directMessages.value.length,
      )
    } else {
      conversations.value = loaded
    }
    if (aid && loaded.some((c) => c.id === aid)) {
      activeConversationId.value = aid
    } else if (loaded.length) {
      activeConversationId.value = loaded[0].id
      saveActiveId(activeConversationId.value)
      wbSidebar.setActiveConversationId(activeConversationId.value)
    }
  },
)
watch(
  () => directMessages.value.length,
  (len, prev) => {
    if (!len) {
      gearNavUserUnlocked.value = false
      return
    }
    /* 从「无消息」到「有消息」时强制重新解锁；避免空会话里提前点解锁绕过 */
    if (!prev) gearNavUserUnlocked.value = false
  },
)
watch(modelMode, (mode) => {
  llmDdOpen.value = null
  if (mode === 'manual') syncManualSelectionFromPreferences()
})
async function startInlineVoice(target: 'direct' | 'make', opts?: { ptt?: boolean }) {
  if (target === 'direct' && (directVoiceListening.value || directVoiceRecognizing.value)) return
  if (target === 'make' && (makeVoiceListening.value || makeVoiceRecognizing.value)) return
  if (!localStorage.getItem('modstore_token')) {
    const msg = '请先登录后再使用语音输入。'
    if (target === 'direct') directError.value = msg
    else window.alert(msg)
    return
  }
  if (voiceListening.value) resetVoiceCaptureUi()
  inlineAsr.abort()
  clearInlineVoicePermissionHint(target)
  __wbState.inlineVoiceTarget = target
  if (opts?.ptt) {
    __wbState.inlineVoicePrefix = ''
    if (target === 'direct') directDraft.value = ''
    else makeComposerInput.value = ''
  } else {
    __wbState.inlineVoicePrefix = target === 'direct' ? directDraft.value : makeComposerInput.value
  }
  if (target === 'direct') {
    directVoiceListening.value = true
    directVoiceRecognizing.value = false
    directError.value = ''
  } else {
    makeVoiceListening.value = true
    makeVoiceRecognizing.value = false
  }
  await inlineAsr.startListening(
    (r) => {
      if (r.text) applyInlineVoiceText(r.text)
    },
    (msg) => {
      const text = String(msg || '语音输入失败')
      if (isMicPermissionError(text)) setInlineVoicePermissionHint(target, text)
      else showAppToast(text, { variant: 'error' })
      if (target === 'direct') {
        if (!isMicPermissionError(text)) directError.value = text
        directVoiceListening.value = false
        directVoiceRecognizing.value = false
      } else {
        makeVoiceListening.value = false
        makeVoiceRecognizing.value = false
      }
      stopInlineVoiceCapture()
    },
    (level) => {
      if (target === 'direct') directVoiceAudioLevel.value = level
    },
  )
}
function onInlineHoldStart(target: 'direct' | 'make', e: PointerEvent) {
  if (__wbState.inlineHoldActive) return
  if (target === 'direct' && directLoading.value) return
  __wbState.inlineHoldActive = true
  __wbState.inlineHoldCancelIntent = false
  __wbState.inlineHoldStartY = e.clientY
  __wbState.inlineHoldPointerId = e.pointerId
  try {
    (e.currentTarget as HTMLElement)?.setPointerCapture(e.pointerId)
  } catch { /* ignore */ }
  void startInlineVoice(target, { ptt: true })
}
function applyMakeCompletion(
  final: WorkbenchOrchestrationSession,
  intent: string,
  handoffSnapshot: PendingHandoff,
): WorkbenchCompletionResult {
  const completion = buildMakeCompletionResult(final, intent, handoffSnapshot)
  makeCompletionResult.value = completion
  pendingHandoff.value = null
  if (intent === 'employee') {
    tryOpenEmployeeSixDimModal(final)
  }
  void scrollMakeFlowToEnd()
  void maybeAutoOpenMakeCompletionInVoiceMode()
  return completion
}
/** 说模式：14/14 完成后自动跳进员工画布（带 packId），避免停在语音页不知道下一步 */
async function maybeAutoOpenMakeCompletionInVoiceMode() {
  if (wbSidebar.activeMode !== 'voice') return
  if (employeeSixDimModalOpen.value) return
  const r = makeCompletionResult.value
  if (!r || r.intent !== 'employee' || !r.primaryRoute) return
  const qr = orchestrationSession.value?.artifact?.quality_report
  if (qr && (qr.critical_failed || qr.runnable === false)) return
  const spoken = String(r.title || '员工包已生成').replace(/。$/, '')
  await speakVoiceShort(`${spoken}，正在打开员工制作画布。`)
  await openMakeCompletionPrimary()
}

  __wbLate1.handleVoicePlanReply = handleVoicePlanReply
  __wbLate1.handleVoicePlanReplySmart = handleVoicePlanReplySmart
  __wbLate1.injectVoiceDuringWork = injectVoiceDuringWork
  __wbLate1.runVoiceChatTurn = runVoiceChatTurn
  __wbLate1.runVoiceS2STurn = runVoiceS2STurn
  __wbLate1.runVoiceUnifiedTurn = runVoiceUnifiedTurn
  __wbLate1.speakVoiceShort = speakVoiceShort

  return {
    ...ctx, onVoiceDismissPlanPanel, handleVoicePlanReplySmart, handleVoicePlanReply, injectVoiceDuringWork,
    runVoiceUnifiedTurn, runVoiceS2STurn, runVoiceChatTurn, speakVoiceShort, _submitVoiceTurn,
    _speakTextAndContinue, startInlineVoice, onInlineHoldStart, applyMakeCompletion, maybeAutoOpenMakeCompletionInVoiceMode,
  }
}

export type useWbHandleVoicePlanReplySmartBinds = ReturnType<typeof useWbHandleVoicePlanReplySmart>

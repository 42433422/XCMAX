import { nextTick } from 'vue'
import { useSpeechRecognition } from '../../composables/useSpeechRecognition'
import type { ASRResult } from '../../composables/asr/types'
import { shouldTriggerVoiceBargeIn } from '../../composables/voiceBargeIn'
import { useVoiceContinuousChat } from '../../composables/useVoiceContinuousChat'
import { buildOrchestrationStatusSummary, hasEmployeePlanContext, isLikelyShortProceedFragment, routeVoiceUtterance } from '../../composables/voiceUtteranceRouter'
import { applyVoiceSessionPatch, buildPlanBriefFromVoiceMessages, sanitizeVoiceUtteranceText, isLikelyAsrEchoNoise, type VoiceTurnClassification } from '../../composables/voiceSessionAgent'
import type { useWbConfirmPlanAndOpenHandoff } from './useWbConfirmPlanAndOpenHandoff'
import { wbLate1 as __wbLate1 } from './wbLate1'

// 拆分自 WorkbenchHomeView.vue（原行 3271–3273, 3451–3489, 3569–3583 …）；逐字迁移，行为不变。
export function useWbDispatchEmployeeVoiceUtterance(ctx: ReturnType<typeof useWbConfirmPlanAndOpenHandoff>) {
  const {
    wbSidebar, pendingHandoff, finalizeLoading, finalizeError, orchestrationSession, orchestrationSessionId,
    pollStop, __wbState, planSession, autoPilotRunning, voiceChecklistPaused, CANVAS_SKILL_INTENT,
    composerIntent, modFrontendEnabled, voiceHumanChatMode, directVoiceListening, makeVoiceListening, streamingTts,
    voiceS2s, voiceUnified, unifiedAsrBridge, voiceUseUnified, voiceUseS2S, voiceUsePhonePipeline,
    voiceMessages, voiceSessionState, voiceError, voiceState, voiceChatPhase, voiceChatBusy,
    voiceAutoSend, inlineAsr, canSpeculateForPartial, appendVoiceUserTurn, handlePhonePartialStable, tryOpenEmployeePlanFromExplicitCommand,
    cancelSpeculativeVoiceTurn, triggerVoiceBargeIn, buildVoiceTopicHint, ensureVoiceEmployeeIntent, shouldRouteVoiceAsEmployee, buildVoiceRouteContext,
    dismissPlanSessionFromVoice, dismissStaleVoicePlanSilently, applyEmployeeSessionClassify, resolveEmployeeClassification, ensureEmployeePlanContextFromVoice, resummarizeVoiceEmployeePlan,
    textsSimilarForFinalize, syncVoiceWorkPhase, requireLoginForWorkbenchUse, intentMeta, canRunOrchestration, stopInlineVoiceCapture,
    stopInlineVoice, dismissPlanSession, friendlyPlanPanelApiError, openPlanSession, confirmSummaryAndStartPlanning, confirmPlanAndOpenHandoff,
  } = ctx

function voiceMicLevelRaw(): number {
  return Math.max(voiceAudioLevel.value, inlineAsr.audioLevel.value)
}
/** 统一语音模式下走单 WS，否则走 FunASR 链 */
const voiceAsrAdapter = {
  get error() {
    return voiceUseUnified.value ? voiceUnified.lastError : inlineAsr.error
  },
  get interimText() {
    return voiceUseUnified.value ? voiceLivePreview : inlineAsr.interimText
  },
  get audioLevel() {
    return voiceUseUnified.value ? voiceUnified.audioLevel : inlineAsr.audioLevel
  },
  get loadingHint() {
    return voiceUseUnified.value ? voiceUnified.loadingHint : inlineAsr.loadingHint
  },
  get activeBackendId() {
    return voiceUseUnified.value ? voiceUnified.activeBackendId : inlineAsr.activeBackendId
  },
  get sessionReady() {
    return voiceUseUnified.value ? voiceUnified.sessionReady : inlineAsr.sessionReady
  },
  startListening: (
    onResult: (r: ASRResult) => void,
    onError: (msg: string) => void,
    onLevel?: (level: number) => void,
    opts?: { continuous?: boolean },
  ) =>
    voiceUseUnified.value
      ? unifiedAsrBridge.startListening(onResult, onError, onLevel, opts)
      : inlineAsr.startListening(onResult, onError, onLevel, opts),
  flushListening: () =>
    voiceUseUnified.value ? unifiedAsrBridge.flushListening() : inlineAsr.flushListening(),
  signalEndOfSpeech: () => {
    if (voiceUseUnified.value) unifiedAsrBridge.signalEndOfSpeech()
    else inlineAsr.signalEndOfSpeech()
  },
  stopListening: () =>
    voiceUseUnified.value ? unifiedAsrBridge.stopListening() : inlineAsr.stopListening(),
  abort: (opts?: { keepMic?: boolean }) =>
    voiceUseUnified.value ? unifiedAsrBridge.abort(opts) : inlineAsr.abort(opts),
}
function handlePhoneUtteranceFinalize(text: string, turnId: string) {
  if (!voiceUsePhonePipeline.value) return
  if (voiceUseUnified.value) {
    voiceUnified.sendUtteranceFinalize(text, turnId)
  } else {
    voiceS2s.sendUtteranceFinalize(text, turnId)
  }
  if (__wbState.s2sProvisionalStarted && !textsSimilarForFinalize(text, voiceMessages.value.filter((m) => m.role === 'user').pop()?.content || '')) {
    if (voiceUseUnified.value) voiceUnified.cancelTurn()
    else voiceS2s.cancelTurn()
    __wbState.s2sProvisionalStarted = false
    if (voiceUseUnified.value) void __wbLate1.runVoiceUnifiedTurn(text, undefined, { skipUserAppend: true, turnId })
    else void __wbLate1.runVoiceS2STurn(text, undefined, { skipUserAppend: true, turnId })
  }
}
async function handleVoiceUtteranceReady(
  text: string,
  ctx: { speculativePartial: string | null },
) {
  if (voiceUsePhonePipeline.value && __wbState.s2sProvisionalStarted && __wbState.s2sProvisionalTurnId) {
    const msgs = [...voiceMessages.value]
    const lastUser = msgs.filter((m) => m.role === 'user').pop()
    if (lastUser && lastUser.content !== text) {
      lastUser.content = text
      voiceMessages.value = msgs
    }
    handlePhoneUtteranceFinalize(text, __wbState.s2sProvisionalTurnId)
    return
  }
  if (ctx.speculativePartial && voiceChatBusy.value && __wbState.voiceStreamHandle) {
    const msgs = [...voiceMessages.value]
    const lastUser = msgs.filter((m) => m.role === 'user').pop()
    if (!lastUser || lastUser.content !== text) {
      appendVoiceUserTurn(text)
    }
    voiceChat.noteSubmitted(text)
    try {
      await __wbState.voiceStreamHandle.done
    } catch {
      /* aborted */
    }
    voiceChatBusy.value = false
    voiceChatPhase.value = 'idle'
    __wbState.voiceStreamHandle = null
    if (composerIntent.value === 'employee') {
      if (await tryOpenEmployeePlanFromExplicitCommand(text, { userAlreadyInThread: true })) {
        return
      }
      const classification = await resolveEmployeeClassification(text)
      applyVoiceSessionPatch(voiceSessionState.value, classification.statePatch)
      if (classification.action !== 'chat' && classification.action !== 'clarify') {
        await dispatchEmployeeVoiceUtterance(text, {
          userAlreadyInThread: true,
          skipReclassify: true,
          prefetchedClassification: classification,
        })
      }
      return
    }
    void applyEmployeeSessionClassify(text)
    return
  }
  await dispatchVoiceUtterance(text, { alreadySubmitted: true })
}
function startSpeculativeVoiceTurn(partialText: string) {
  if (voiceChatBusy.value) return
  streamingTts.warmUp()
  void __wbLate1.runVoiceChatTurn(partialText, undefined, { skipUserAppend: true, speculative: true })
}
const voiceChat = useVoiceContinuousChat({
  asr: voiceAsrAdapter as ReturnType<typeof useSpeechRecognition>,
  isAsrReady: () => voiceAsrAdapter.sessionReady.value,
  getAsrBackendId: () =>
    voiceUseUnified.value ? 'funasr' : voiceAsrAdapter.activeBackendId.value,
  signalAsrEndOfSpeech: () => voiceAsrAdapter.signalEndOfSpeech(),
  voiceUsePhonePipeline: () => voiceUsePhonePipeline.value,
  voiceUseS2S: () => voiceUseS2S.value,
  usePhoneLatency: () => voiceUsePhonePipeline.value,
  onS2SPartialStable: handlePhonePartialStable,
  onS2SUtteranceFinalize: handlePhoneUtteranceFinalize,
  autoSend: voiceAutoSend,
  voiceState,
  voiceChatPhase,
  isVoiceTargetActive: () => __wbState.inlineVoiceTarget === 'voice',
  setVoiceTarget: () => { __wbState.inlineVoiceTarget = 'voice' },
  clearVoiceTarget: () => { __wbState.inlineVoiceTarget = null },
  beforeStartListening: () => {
    if (directVoiceListening.value) void stopInlineVoice('direct')
    if (makeVoiceListening.value) void stopInlineVoice('make')
    if (__wbState.inlineVoiceTarget && __wbState.inlineVoiceTarget !== 'voice') {
      inlineAsr.abort()
      stopInlineVoiceCapture()
    }
  },
  onUtteranceReady: handleVoiceUtteranceReady,
  onSpeculativeStart: startSpeculativeVoiceTurn,
  onSpeculativeCancel: cancelSpeculativeVoiceTurn,
  onBargeIn: () => triggerVoiceBargeIn(),
  onAsrDuringTts: (level: number) => {
    if (!voiceAutoSend.value) return false
    const ep = voiceUseUnified.value ? { speechLevel: 0.012 } : { speechLevel: 0.012 }
    const ttsOn = voiceUseUnified.value
      ? voiceUnified.isPlaying()
      : voiceUseS2S.value
        ? voiceS2s.isPlaying()
        : streamingTts.state.value !== 'idle'
    if (!ttsOn) return false
    if (shouldTriggerVoiceBargeIn(level, ep.speechLevel, true)) {
      triggerVoiceBargeIn()
      return true
    }
    return false
  },
  isTtsPlaying: () =>
    voiceUseUnified.value
      ? voiceUnified.isPlaying()
      : voiceUseS2S.value
        ? voiceS2s.isPlaying()
        : streamingTts.state.value !== 'idle',
  canSpeculate: canSpeculateForPartial,
  isChatBusy: () => voiceChatBusy.value,
})
const {
  voiceDraft,
  voiceTranscript,
  voiceLivePreview,
  voiceListening,
  voiceAudioLevel,
  micPausedByUser: voiceMicPausedByUser,
  isSpeculating: voiceSpeculating,
} = voiceChat
function noteVoiceSubmitted(text: string) {
  voiceChat.noteSubmitted(text)
}
function resumeVoiceListeningAfterTurn() {
  if (wbSidebar.activeMode !== 'voice') return
  if (voiceMicPausedByUser.value) return
  setTimeout(() => {
    voiceChat.ensureListening()
    void drainVoiceUtteranceQueue()
  }, 300)
}
async function drainVoiceUtteranceQueue() {
  if (__wbState.voiceUtteranceDraining || voiceChatBusy.value || !__wbState.voiceUtteranceQueue.length) return
  const next = __wbState.voiceUtteranceQueue.shift()
  if (!next) return
  __wbState.voiceUtteranceDraining = true
  try {
    await dispatchVoiceUtteranceCore(next, { userAlreadyInThread: true })
  } finally {
    __wbState.voiceUtteranceDraining = false
    if (__wbState.voiceUtteranceQueue.length) void drainVoiceUtteranceQueue()
  }
}
async function dispatchVoiceUtterance(
  text: string,
  opts?: { alreadySubmitted?: boolean; fromTypedComposer?: boolean },
) {
  const content = sanitizeVoiceUtteranceText(text)
  if (!content) return
  if (
    !voiceHumanChatMode.value &&
    !opts?.fromTypedComposer &&
    !isLikelyShortProceedFragment(content) &&
    isLikelyAsrEchoNoise(content, buildVoiceTopicHint(content))
  ) {
    return
  }
  if (!requireLoginForWorkbenchUse()) return
  voiceChat.clearContinuousSilenceTimer()
  if (opts?.fromTypedComposer) {
    appendVoiceUserTurn(content)
    noteVoiceSubmitted(content)
  } else if (!opts?.alreadySubmitted) {
    noteVoiceSubmitted(content)
  }

  if (voiceChatBusy.value) {
    __wbState.voiceUtteranceQueue.push(content)
    const last = voiceMessages.value[voiceMessages.value.length - 1]
    if (!last || last.role !== 'user' || last.content !== content) {
      appendVoiceUserTurn(content)
    }
    return
  }
  await dispatchVoiceUtteranceCore(content)
}
async function executeLegacyVoiceRoute(
  action: ReturnType<typeof routeVoiceUtterance>,
  content: string,
  opts?: { userAlreadyInThread?: boolean },
) {
  switch (action.type) {
    case 'cancel_work':
      pollStop.value = true
      await __wbLate1.speakVoiceShort('好的，已停止当前制作。')
      return
    case 'status_query':
      await __wbLate1.speakVoiceShort(
        buildOrchestrationStatusSummary(orchestrationSession.value?.steps) ||
          (pendingHandoff.value ? '草稿已准备好，可以说开始生成。' : '当前没有进行中的制作。'),
      )
      return
    case 'confirm_generate':
      await __wbLate1.runOrchestration()
      await __wbLate1.speakVoiceShort('已开始生成，你可以在上方查看进度。')
      resumeVoiceListeningAfterTurn()
      return
    case 'inject':
      await __wbLate1.injectVoiceDuringWork(content)
      return
    case 'plan_reply':
      await __wbLate1.handleVoicePlanReply(content)
      return
    case 'new_task':
      await openPlanSessionFromVoice(content)
      resumeVoiceListeningAfterTurn()
      return
    case 'chat':
    default:
      await __wbLate1.runVoiceChatTurn(content, undefined, { skipUserAppend: opts?.userAlreadyInThread })
      return
  }
}
async function resumeVoiceAfterChatTurn(useTts: boolean) {
  if (useTts && voiceUseUnified.value) {
    voiceState.value = 'reporting'
    await voiceUnified.whenAudioIdle()
  } else if (useTts && voiceUseS2S.value) {
    voiceState.value = 'reporting'
    await voiceS2s.whenAudioIdle()
  } else if (useTts && streamingTts.state.value !== 'idle') {
    voiceState.value = 'reporting'
    await streamingTts.whenIdle()
  }
  voiceState.value = 'idle'
  resumeVoiceListeningAfterTurn()
}
async function dispatchEmployeeVoiceUtterance(
  content: string,
  opts?: {
    userAlreadyInThread?: boolean
    skipReclassify?: boolean
    prefetchedClassification?: VoiceTurnClassification
  },
) {
  const routeCtx = buildVoiceRouteContext()
  const fast = routeVoiceUtterance({ text: content, ...routeCtx })
  if (['cancel_work', 'status_query', 'confirm_generate', 'inject'].includes(fast.type)) {
    return executeLegacyVoiceRoute(fast, content, opts)
  }

  const classification =
    opts?.prefetchedClassification ?? (await resolveEmployeeClassification(content))
  applyVoiceSessionPatch(voiceSessionState.value, classification.statePatch)

  const skipUserAppend = opts?.userAlreadyInThread
  const chatHint =
    classification.replyHint ||
    (classification.action === 'clarify'
      ? '先复述你对用户意思的理解，并追问 1-2 个关键点；不要开规划或画流程图。'
      : undefined)

  switch (classification.action) {
    case 'cancel_work':
      pollStop.value = true
      voiceSessionState.value.stage = 'exploring'
      await __wbLate1.speakVoiceShort('好的，已停止当前制作。')
      return
    case 'status':
      await __wbLate1.speakVoiceShort(
        buildOrchestrationStatusSummary(orchestrationSession.value?.steps) ||
          (pendingHandoff.value ? '草稿已准备好，可以说开始生成。' : '当前没有进行中的制作。'),
      )
      return
    case 'dismiss_plan':
      await dismissPlanSessionFromVoice()
      await __wbLate1.runVoiceChatTurn(
        content,
        chatHint || '用户质疑过早开规划。说明当前并未执行制作，问是否现在要进入需求规划。',
        { skipUserAppend },
      )
      return
    case 'open_plan':
      if (!voiceSessionState.value.readyToPlan && classification.confidence < 0.65) {
        dismissStaleVoicePlanSilently()
        voiceSessionState.value.stage = 'clarifying'
        await __wbLate1.runVoiceChatTurn(
          content,
          chatHint || '目标尚未明确。先复述理解并追问职责、场景或产出，不要开规划面板。',
          { skipUserAppend },
        )
        return
      }
      ensureEmployeePlanContextFromVoice(content)
      voiceSessionState.value.readyToPlan = true
      dismissStaleVoicePlanSilently()
      await openPlanSessionFromVoice(content, { skipUserAppend })
      voiceSessionState.value.stage = 'planning'
      resumeVoiceListeningAfterTurn()
      return
    case 'pause_checklist':
      voiceChecklistPaused.value = true
      await __wbLate1.speakVoiceShort('好的，先不自动制作；需要时说开始或确认生成。')
      resumeVoiceListeningAfterTurn()
      return
    case 'update_plan':
    case 'confirm_plan':
      await __wbLate1.handleVoicePlanReplySmart(content, classification, { skipUserAppend })
      return
    case 'clarify':
    case 'chat':
    default:
      dismissStaleVoicePlanSilently()
      if (voiceSessionState.value.lastUserTone === 'complaint' && planSession.value) {
        dismissPlanSession()
        voiceSessionState.value.stage = 'exploring'
        voiceSessionState.value.readyToPlan = false
        syncVoiceWorkPhase()
      }
      await __wbLate1.runVoiceChatTurn(content, chatHint, { skipUserAppend })
      return
  }
}
async function dispatchVoiceUtteranceCore(
  content: string,
  opts?: { userAlreadyInThread?: boolean; fromTypedComposer?: boolean },
) {
  voiceError.value = ''
  if (voiceHumanChatMode.value) {
    dismissStaleVoicePlanSilently()
    await __wbLate1.runVoiceChatTurn(content, undefined, {
      skipUserAppend: opts?.userAlreadyInThread || opts?.fromTypedComposer,
      fromTypedComposer: opts?.fromTypedComposer,
    })
    return
  }
  ensureVoiceEmployeeIntent(content)
  if (shouldRouteVoiceAsEmployee(content)) {
    await dispatchEmployeeVoiceUtterance(content, opts)
    return
  }
  const action = routeVoiceUtterance({
    text: content,
    ...buildVoiceRouteContext(),
  })
  await executeLegacyVoiceRoute(action, content, opts)
}
/** 执行清单阶段：口头「开始/确认生成」→ 确认清单并启动 14 步编排 */
async function confirmEmployeeChecklistAndRunFromVoice() {
  if (autoPilotRunning.value || finalizeLoading.value) {
    await __wbLate1.speakVoiceShort('制作已在进行，请稍候并向上查看进度。')
    return
  }
  const ps = planSession.value
  if (pendingHandoff.value && canRunOrchestration.value) {
    await __wbLate1.speakVoiceShort('好的，正在根据清单开始制作，请稍候。')
    try {
      await __wbLate1.runOrchestration()
      if (finalizeError.value) {
        await __wbLate1.speakVoiceShort(`制作启动失败：${finalizeError.value}`)
      } else if (!orchestrationSessionId.value) {
        await __wbLate1.speakVoiceShort('制作未能启动，请点「确认清单并进入制作」重试。')
      }
    } catch (e) {
      await __wbLate1.speakVoiceShort(friendlyPlanPanelApiError(e))
    }
    return
  }
  if (!ps || ps.phase !== 'checklist') {
    await __wbLate1.speakVoiceShort('当前没有待确认的执行清单，请先说需求或点「确认清单并进入制作」。')
    return
  }
  if (ps.loading) {
    await __wbLate1.speakVoiceShort('清单还在生成，请稍候。')
    return
  }
  await __wbLate1.speakVoiceShort('好的，正在根据清单开始制作，请稍候。')
  confirmPlanAndOpenHandoff()
  voiceSessionState.value.stage = 'executing'
  syncVoiceWorkPhase()
  await nextTick()
  if (!pendingHandoff.value) {
    await __wbLate1.speakVoiceShort('未能生成制作草稿，请点击「确认清单并进入制作」。')
    return
  }
  if (!canRunOrchestration.value) {
    await __wbLate1.speakVoiceShort('制作草稿不完整，请补充描述后重试。')
    return
  }
  try {
    await __wbLate1.runOrchestration()
    if (finalizeError.value) {
      await __wbLate1.speakVoiceShort(`制作启动失败：${finalizeError.value}`)
    } else if (!orchestrationSessionId.value) {
      await __wbLate1.speakVoiceShort('制作未能启动，请点「确认清单并进入制作」重试。')
    }
  } catch (e) {
    await __wbLate1.speakVoiceShort(friendlyPlanPanelApiError(e))
  }
}
async function voiceEmployeePlanPostOpen(triggerText: string) {
  const ps = planSession.value
  if (!ps || ps.intentKey !== 'employee') return
  const hasContext = hasEmployeePlanContext(
    voiceSessionState.value,
    voiceMessages.value,
    triggerText,
  )

  if (ps.summaryNeedsClarification && hasContext) {
    await resummarizeVoiceEmployeePlan(true)
  }
  if (!ps.summaryNeedsClarification) {
    await confirmSummaryAndStartPlanning()
    await __wbLate1.speakVoiceShort('已根据你的描述进入详细规划，你可以继续补充或直接回答我的问题。')
    return
  }
  await __wbLate1.speakVoiceShort('摘要里还有几点待确认，请继续用语音或文字补充。')
}
async function openPlanSessionFromVoice(
  text: string,
  opts?: { skipUserAppend?: boolean },
) {
  const utterance = sanitizeVoiceUtteranceText(text)
  ensureVoiceEmployeeIntent(utterance)
  const intent = composerIntent.value || CANVAS_SKILL_INTENT
  const wantsModFrontend = intent === 'mod' && modFrontendEnabled.value
  ensureEmployeePlanContextFromVoice(utterance)
  const briefCore =
    intent === 'employee'
      ? buildPlanBriefFromVoiceMessages(
          voiceSessionState.value,
          voiceMessages.value,
          utterance,
        )
      : utterance
  const payloadParts = [briefCore]
  if (intent === 'mod') {
    payloadParts.push(
      wantsModFrontend
        ? '【制作选项】本次需要为 Mod 生成可路由的定制 Vue 前端页面。'
        : '【制作选项】本次暂不生成定制前端。',
    )
  }
  payloadParts.push(`【语音输入 · ${intentMeta.value.title}】`)
  await openPlanSession({
    fullBrief: payloadParts.join('\n\n'),
    displayBrief: utterance,
    files: [],
    generateFrontend: wantsModFrontend,
  })
  if (!opts?.skipUserAppend) {
    appendVoiceUserTurn(utterance)
  }
  if (intent === 'employee') {
    await voiceEmployeePlanPostOpen(utterance)
    return
  }
  await __wbLate1.speakVoiceShort('已开始规划，请继续补充需求或直接回答澄清问题。')
}

  return {
    ...ctx, voiceMicLevelRaw, voiceAsrAdapter, handlePhoneUtteranceFinalize, handleVoiceUtteranceReady,
    startSpeculativeVoiceTurn, voiceChat, voiceDraft, voiceTranscript, voiceLivePreview,
    voiceListening, voiceAudioLevel, voiceMicPausedByUser, voiceSpeculating, noteVoiceSubmitted,
    resumeVoiceListeningAfterTurn, drainVoiceUtteranceQueue, dispatchVoiceUtterance, executeLegacyVoiceRoute, resumeVoiceAfterChatTurn,
    dispatchEmployeeVoiceUtterance, dispatchVoiceUtteranceCore, confirmEmployeeChecklistAndRunFromVoice, voiceEmployeePlanPostOpen, openPlanSessionFromVoice,
  }
}

export type useWbDispatchEmployeeVoiceUtteranceBinds = ReturnType<typeof useWbDispatchEmployeeVoiceUtterance>

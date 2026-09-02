import { computed, nextTick, watch } from 'vue'
import { api } from '../../api'
import { requestMicInUserGesture } from '../../composables/asr/micPreflight'
import { unlockVoiceAudioPlayback } from '../../composables/voiceDevice'
import { resetVoiceSessionState } from '../../composables/voiceSessionAgent'
import type { useWbDispatchEmployeeVoiceUtterance } from './useWbDispatchEmployeeVoiceUtterance'
import type { SiriOrbMode } from './types'

// 拆分自 WorkbenchHomeView.vue（原行 2602–2614, 2617–2628, 2630–2639 …）；逐字迁移，行为不变。
export function useWbDrawWaveform(ctx: ReturnType<typeof useWbDispatchEmployeeVoiceUtterance>) {
  const {
    wbSidebar, wbNav, draft, pendingHandoff, finalizeLoading, finalizeError,
    orchestrationSession, orchestrationSessionId, pollStop, orchPhase, orchestrationEtaSeconds, __wbState,
    orchTimingStartMs, linkBusy, planSession, planReplyDraft, autoPilotRunning, CANVAS_SKILL_INTENT,
    composerIntent, activeGear, isMakeToolbarIntentActive, platformChatMode, voiceCasualChatMode, voiceSessionModeForIntent,
    clearMakePanelsForCasualChat, persistPlatformChatMode, directDraft, directAttachedFiles, directLoading, directError,
    directIsDragging, editingMessageId, editingDraft, streamingTts, speakingMessageId, stopDirectTtsPlayback,
    voiceMessages, voiceSessionState, voiceError, voiceMicFallbackHint, voiceState, voiceReport,
    waveformCanvas, voiceChatPhase, voiceWorkPhase, voiceChatBusy, clearInjectQueue, voiceAutoSend,
    WAVE_BAR_COUNT, waveBarHeights, voiceMicLevelRaw, inlineAsr, voiceAsrAdapter, cancelSpeculativeVoiceTurn,
    voiceChat, voiceLivePreview, voiceListening, voiceMicPausedByUser, voiceDraft, voiceAudioLevel,
    voiceTranscript, voiceAssistantSpeaking, ensureActiveConversation, directDragDepth, dispatchVoiceUtterance, syncVoiceWorkPhase,
    llmDdOpen, stopOrchestrationElapsedTicker, clearMakeProgressCache, dismissPlanSession, dismissPendingHandoff,
  } = ctx

function resumeVoiceListeningInSayMode() {
  if (wbSidebar.activeMode !== 'voice') return
  voiceError.value = ''
  voiceMicFallbackHint.value = ''
  if (voiceMicPausedByUser.value) {
    resumeVoiceMic()
    return
  }
  if (!voiceListening.value) {
    streamingTts.warmUp()
    void startVoiceRecognition({ fresh: true })
  }
}
/** 留在当前档位，进入一档正常聊天（不跳侧栏「聊」、不触发制作/Skill 任务） */
function enablePlatformChatMode() {
  const stayMode = wbSidebar.activeMode
  voiceCasualChatMode.value = true
  persistPlatformChatMode(true)
  composerIntent.value = CANVAS_SKILL_INTENT
  clearMakePanelsForCasualChat()
  resumeVoiceListeningInSayMode()
  if (wbSidebar.activeMode !== stayMode) {
    wbSidebar.setActiveMode(stayMode)
    activeGear.value = stayMode
  }
}
function disablePlatformChatMode() {
  const stayMode = wbSidebar.activeMode
  voiceCasualChatMode.value = false
  persistPlatformChatMode(false)
  resumeVoiceListeningInSayMode()
  if (wbSidebar.activeMode !== stayMode) {
    wbSidebar.setActiveMode(stayMode)
    activeGear.value = stayMode
  }
}
/** 平台模式：隐藏做 Mod/做员工等，留在当前档位（说/做），不跳到侧栏「聊」 */
function togglePlatformChatMode() {
  if (platformChatMode.value) disablePlatformChatMode()
  else enablePlatformChatMode()
}
/** 再点已选中的「做 Mod / 做员工 / Skill 组」→ 退出制作态，留在「说/做」常态化聊天 */
function exitMakeToolbarToCasualChat() {
  const stayMode = wbSidebar.activeMode
  voiceCasualChatMode.value = true
  persistPlatformChatMode(false)
  composerIntent.value = CANVAS_SKILL_INTENT
  clearMakePanelsForCasualChat()
  resumeVoiceListeningInSayMode()
  if (wbSidebar.activeMode !== stayMode) {
    wbSidebar.setActiveMode(stayMode)
    activeGear.value = stayMode
  }
}
function switchMakeIntent(intent: string) {
  if (isMakeToolbarIntentActive(intent)) {
    if (
      planSession.value ||
      autoPilotRunning.value ||
      pendingHandoff.value ||
      finalizeLoading.value ||
      orchPhase.value === 'running' ||
      orchPhase.value === 'estimating'
    ) {
      return
    }
    exitMakeToolbarToCasualChat()
    return
  }
  voiceCasualChatMode.value = false
  if (platformChatMode.value) {
    persistPlatformChatMode(false)
  }
  composerIntent.value = intent
  if (wbSidebar.activeMode === 'voice') {
    resetVoiceSessionState(voiceSessionState, voiceSessionModeForIntent(intent))
    voiceSessionState.value.stage = 'exploring'
    voiceSessionState.value.readyToPlan = false
    syncVoiceWorkPhase()
  }
}
function drawWaveform() {
  const canvas = waveformCanvas.value
  if (!canvas) {
    __wbState.waveRafId = requestAnimationFrame(drawWaveform)
    return
  }
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    __wbState.waveRafId = requestAnimationFrame(drawWaveform)
    return
  }
  const dpr = window.devicePixelRatio || 1
  const w = canvas.clientWidth
  const h = canvas.clientHeight
  canvas.width = w * dpr
  canvas.height = h * dpr
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)

  const levelRaw = voiceMicLevelRaw()
  const asrLive = voiceListening.value && inlineAsr.sessionReady.value
  const visBoost = Math.min(1, Math.pow(Math.max(levelRaw, 0.0005), 0.5) * 1.65)
  let level: number
  if (asrLive && levelRaw >= 0.004) {
    level = visBoost
  } else if (asrLive) {
    // 已连接但电平弱：可见呼吸动画 + 微量真实电平
    level = Math.max(visBoost, 0.05 + 0.04 * (0.5 + 0.5 * Math.sin(Date.now() / 480)))
  } else if (levelRaw >= 0.004) {
    level = visBoost
  } else {
    level = 0.04 + 0.035 * (0.5 + 0.5 * Math.sin(Date.now() / 900))
  }
  const weakMic = asrLive && levelRaw < 0.004
  const barW = Math.max(2, (w / WAVE_BAR_COUNT) - 2)
  const gap = 2
  const maxH = h - 2

  for (let i = 0; i < WAVE_BAR_COUNT; i++) {
    // 中间高两边低的包络
    const center = WAVE_BAR_COUNT / 2
    const dist = Math.abs(i - center) / center
    const envelope = 1 - dist * dist
    // 目标高度
    const target = 2 + level * envelope * maxH * (0.6 + 0.4 * Math.sin(Date.now() / 150 + i * 0.7))
    // 平滑过渡
    waveBarHeights[i] += (target - waveBarHeights[i]) * 0.3
    const bh = Math.max(2, waveBarHeights[i])
    const x = i * (barW + gap) + gap
    const y = (h - bh) / 2
    const alpha = weakMic ? 0.22 + level * 0.35 * envelope : 0.3 + level * 0.5 * envelope
    ctx.fillStyle = weakMic
      ? `rgba(251,191,36,${alpha})`
      : `rgba(129,140,248,${alpha})`
    ctx.beginPath()
    ctx.roundRect(x, y, barW, bh, 1.5)
    ctx.fill()
  }

  __wbState.waveRafId = requestAnimationFrame(drawWaveform)
}
const voiceAsrActiveId = computed(() => voiceAsrAdapter.activeBackendId.value)
const voiceAsrBackendLabel = computed(() => {
  if (!inlineAsr.sessionReady.value) return ''
  const id = voiceAsrActiveId.value
  if (id === 'funasr') return '服务端'
  if (id === 'whisper-web') return '本地模型'
  if (id === 'webspeech') return '浏览器'
  return ''
})
/** let 赋值的 ref 在模板中不会自动解包，需 computed 桥接 VoiceDock v-model */
const voiceDockDraft = computed({
  get: () => voiceDraft.value,
  set: (v: string) => { voiceDraft.value = v },
})
const showVoiceWaveform = computed(() => {
  if (voiceMicPausedByUser.value) return false
  if (wbSidebar.activeMode !== 'voice') return false
  return (
    (voiceListening.value && voiceAsrAdapter.sessionReady.value)
    || Boolean(voiceAsrAdapter.loadingHint.value)
    || voiceState.value === 'listening'
    || voiceAssistantSpeaking.value
  )
})
const voiceAsrConnecting = computed(
  () =>
    Boolean(voiceAsrAdapter.loadingHint.value) &&
    !voiceAsrAdapter.sessionReady.value &&
    !voiceMicPausedByUser.value,
)
const voiceAsrListening = computed(
  () => voiceListening.value && voiceAsrAdapter.sessionReady.value && !voiceMicPausedByUser.value,
)
/** 说模式：用户停顿后 ASR 收尾或 LLM 处理前 */
const voiceDockRecognizing = computed(
  () =>
    !voiceMicPausedByUser.value &&
    voiceListening.value &&
    (voiceState.value === 'processing' ||
      Boolean(
        (voiceTranscript.value || voiceLivePreview.value || voiceAsrAdapter.interimText.value) &&
          !voiceAsrConnecting.value,
      )),
)
watch(showVoiceWaveform, (v) => {
  if (v) {
    waveBarHeights.fill(2)
    nextTick(() => {
      cancelAnimationFrame(__wbState.waveRafId)
      __wbState.waveRafId = requestAnimationFrame(drawWaveform)
    })
  } else {
    cancelAnimationFrame(__wbState.waveRafId)
    __wbState.waveRafId = 0
  }
})
watch(waveformCanvas, (el) => {
  if (el && showVoiceWaveform.value) {
    cancelAnimationFrame(__wbState.waveRafId)
    waveBarHeights.fill(2)
    __wbState.waveRafId = requestAnimationFrame(drawWaveform)
  }
})
async function onVoiceDockSend() {
  const text = String(voiceDraft.value || voiceDockDraft.value || '').trim()
  if (!text) return
  voiceError.value = ''
  voiceMicFallbackHint.value = ''
  if (
    voiceChatBusy.value ||
    streamingTts.state.value !== 'idle' ||
    __wbState.voiceStreamHandle
  ) {
    cancelSpeculativeVoiceTurn()
    streamingTts.stop()
    __wbState.voiceStreamHandle?.abort()
    __wbState.voiceStreamHandle = null
    voiceChatBusy.value = false
    voiceChatPhase.value = 'idle'
    voiceState.value = 'idle'
  }
  voiceDraft.value = ''
  voiceDockDraft.value = ''
  await dispatchVoiceUtterance(text, { fromTypedComposer: true })
}
function onVoiceMicToggle() {
  if (voiceMicPausedByUser.value) {
    requestMicInUserGesture()
    void unlockVoiceAudioPlayback()
    voiceError.value = ''
    voiceMicFallbackHint.value = ''
    resumeVoiceMic()
    return
  }
  void forcePauseVoiceSession()
}
function resumeVoiceMic() {
  if (wbSidebar.activeMode !== 'voice') return
  voiceMicPausedByUser.value = false
  voiceError.value = ''
  voiceMicFallbackHint.value = ''
  void startVoiceRecognition({ fresh: true })
}
async function forcePauseVoiceSession() {
  voiceChat.clearContinuousSilenceTimer()
  voiceChat.stopSilenceWatchdog()
  cancelSpeculativeVoiceTurn()
  __wbState.voiceStreamHandle?.abort()
  __wbState.voiceStreamHandle = null
  streamingTts.stop()
  voiceChatBusy.value = false
  voiceChatPhase.value = 'idle'

  let text = voiceTranscript.value.trim() || voiceDraft.value.trim()
  if (voiceListening.value || __wbState.inlineVoiceTarget === 'voice') {
    try {
      const stopped = (await stopVoiceAsr()).trim()
      if (stopped) text = stopped
    } catch {
      /* ignore */
    }
  }

  voiceListening.value = false
  voiceAudioLevel.value = 0
  voiceState.value = 'idle'
  voiceReport.value = ''
  voiceTranscript.value = ''
  voiceMicPausedByUser.value = true

  if (text && voiceChat.hasFreshCapture(text) && voiceAutoSend.value) {
    try {
      await dispatchVoiceUtterance(text)
    } catch {
      voiceDraft.value = text
    }
  } else if (text) {
    voiceDraft.value = text
  }
}
function resetVoiceListenSession() {
  voiceChat.resetListenSession()
}
function resetVoiceCaptureUi() {
  voiceChat.resetCaptureUi()
}
async function finishContinuousUtterance() {
  await voiceChat.finishUtterance()
}
async function activateVoiceContinuous(opts?: { submitPending?: boolean }) {
  voiceError.value = ''
  voiceMicFallbackHint.value = ''
  if (voiceMicPausedByUser.value) return
  const pending = voiceTranscript.value.trim() || voiceDraft.value.trim()
  if (opts?.submitPending !== false && pending) {
    await finishContinuousUtterance()
    return
  }
  if (!voiceListening.value) {
    void startVoiceRecognition({ fresh: true })
  } else if (pending && voiceChat.hasFreshCapture(pending)) {
    voiceChat.clearContinuousSilenceTimer()
  }
}
const voiceOrbMode = computed<SiriOrbMode>(() => {
  if (voiceError.value) return 'idle'
  if (voiceListening.value || voiceState.value === 'listening') return 'listening'
  if (voiceAssistantSpeaking.value && wbSidebar.activeMode === 'voice') return 'reporting'
  if (voiceState.value === 'processing' || voiceState.value === 'reporting') return voiceState.value
  return 'idle'
})
const voiceOrbHint = computed(() => {
  if (voiceAssistantSpeaking.value && wbSidebar.activeMode === 'voice') return '点击打断播报'
  if (voiceListening.value || voiceState.value === 'listening') return '正在听，可直接说话'
  if (voiceWorkPhase.value === 'orchestrating') return '制作中，可直接说话补充'
  if (voiceChatPhase.value === 'streaming') return '思考中，可直接说话打断'
  return ''
})
const voiceOrbActive = computed(
  () =>
    voiceListening.value ||
    voiceState.value === 'listening' ||
    voiceState.value === 'processing' ||
    voiceState.value === 'reporting' ||
    voiceAssistantSpeaking.value ||
    voiceWorkPhase.value === 'orchestrating',
)
const voiceStatusText = computed(() => {
  if (voiceWorkPhase.value === 'orchestrating') return '正在制作，你可以随时说话补充或问进度。'
  if (voiceWorkPhase.value === 'planning') return '需求规划中，直接说话参与澄清。'
  if (voiceWorkPhase.value === 'handoff') return '草稿已就绪，说「开始生成」或点下方按钮。'
  if (voiceState.value === 'listening') return '直接说需求，停顿后自动发送。'
  if (voiceChatPhase.value === 'streaming') return '正在思考，你可以随时说话打断。'
  if (voiceState.value === 'reporting' || streamingTts.state.value !== 'idle') return 'AI 回复中，说完后会继续聆听…'
  if (
    wbNav.isMobile &&
    wbSidebar.activeMode === 'voice' &&
    !voiceListening.value &&
    !voiceMicPausedByUser.value
  ) {
    return '点右下角 ▶ 开始说，也可以直接打字。'
  }
  if (wbNav.isMobile && voiceMicPausedByUser.value) {
    return '麦克风暂停着，想继续说就点 ▶；也可以先打字。'
  }
  return '点一下语音球或直接打字，我们先把话聊顺。'
})
function isGearAxisLocked() {
  const hasInput =
    Boolean(String(draft.value || '').trim()) ||
    Boolean(String(directDraft.value || '').trim()) ||
    Boolean(String(voiceDraft.value || '').trim()) ||
    Boolean(String(planReplyDraft.value || '').trim()) ||
    directAttachedFiles.value.length > 0
  const hasTask =
    Boolean(planSession.value) ||
    Boolean(pendingHandoff.value) ||
    Boolean(finalizeLoading.value) ||
    Boolean(linkBusy.value) ||
    Boolean(orchestrationSession.value?.steps?.length)
  return hasInput || hasTask
}
function newConversationHandler() {
  if (__wbState.currentStreamHandle) {
    __wbState.currentStreamHandle.abort()
    __wbState.currentStreamHandle = null
  }
  directLoading.value = false
  stopDirectTtsPlayback()
  speakingMessageId.value = ''
  editingMessageId.value = ''
  editingDraft.value = ''
  directDraft.value = ''
  directError.value = ''
  directIsDragging.value = false
  directDragDepth.value = 0
  llmDdOpen.value = null
  orchestrationSession.value = null
  orchestrationSessionId.value = ''
  pollStop.value = true
  stopOrchestrationElapsedTicker()
  orchPhase.value = 'idle'
  orchTimingStartMs.value = null
  orchestrationEtaSeconds.value = null
  finalizeLoading.value = false
  finalizeError.value = ''
  const files = directAttachedFiles.value.slice()
  directAttachedFiles.value = []
  for (const item of files as Array<{ docId?: string }>) {
    if (item.docId) {
      void api.knowledgeDeleteDocument(item.docId).catch(() => {
      })
    }
  }
  resetVoiceSession({ resumeListening: true })
  ensureActiveConversation({ forceNew: true })
}
/** 清空语音会话（新对话 / 重置） */
function resetVoiceSession(opts?: { resumeListening?: boolean }) {
  interruptVoice()
  __wbState.voiceStreamHandle?.abort()
  __wbState.voiceStreamHandle = null
  voiceMessages.value = []
  voiceDraft.value = ''
  voiceTranscript.value = ''
  voiceLivePreview.value = ''
  __wbState.voiceUtteranceQueue = []
  voiceReport.value = ''
  voiceError.value = ''
  voiceMicFallbackHint.value = ''
  voiceMicPausedByUser.value = false
  resetVoiceListenSession()
  voiceChatBusy.value = false
  voiceChatPhase.value = 'idle'
  voiceState.value = 'idle'
  streamingTts.stop()
  streamingTts.resetStream()
  clearInjectQueue()
  dismissPlanSession()
  dismissPendingHandoff()
  resetVoiceSessionState(
    voiceSessionState,
    composerIntent.value === 'employee' ? 'employee' : composerIntent.value === 'mod' ? 'mod' : 'skill',
  )
  clearMakeProgressCache()
  syncVoiceWorkPhase()
  if (opts?.resumeListening) {
    nextTick(() => void startVoiceRecognition({ fresh: true }))
  }
}
function onOrbClick() {
  void unlockVoiceAudioPlayback()
  if (voiceError.value) {
    voiceError.value = ''
  }
  voiceMicFallbackHint.value = ''
  if (wbNav.isMobile && (voiceMicPausedByUser.value || !voiceListening.value)) {
    requestMicInUserGesture()
  }
  if (
    voiceState.value === 'processing' ||
    voiceState.value === 'reporting' ||
    streamingTts.state.value !== 'idle'
  ) {
    interruptVoice()
    setTimeout(() => activateVoiceContinuous({ submitPending: false }), 400)
  } else if (voiceListening.value || voiceState.value === 'listening') {
    void finishContinuousUtterance()
  } else {
    voiceMicPausedByUser.value = false
    void activateVoiceContinuous({ submitPending: false })
  }
}
/** AI 说完话后自动开始听 */
async function speakTextAndListen(text: string) {
  voiceState.value = 'reporting'
  try {
    await streamingTts.speak(text)
  } finally {
    voiceReport.value = ''
    void activateVoiceContinuous({ submitPending: false })
  }
}
function _toggleVoiceListening() {
  if (voiceListening.value) {
    void stopVoiceRecognition()
    return
  }
  voiceError.value = ''
  void startVoiceRecognition()
}
async function stopVoiceAsr(): Promise<string> {
  return voiceChat.stopAsr()
}
function _onVoiceAsrError(msg: string) {
  const result = voiceChat.onAsrError(msg)
  if (!result) return
  if (result.msg && !result.retry) {
    voiceError.value = result.msg
  } else if (result.msg) {
    voiceError.value = result.msg
  }
  voiceReport.value = ''
  if (result.retry) {
    const fresh = result.fresh !== false
    setTimeout(() => startVoiceRecognition({ fresh }), result.delayMs ?? 400)
  }
}
async function startVoiceRecognition(opts?: { fresh?: boolean }) {
  if (voiceChat.getSubmitLock()) return
  if (voiceMicPausedByUser.value && opts?.fresh !== false) return
  voiceError.value = ''
  voiceMicFallbackHint.value = ''
  const res = await voiceChat.startListening(opts)
  if (res?.error) {
    const soft = /权限|Permission|NotAllowed|NotReadable|NotFound|denied|启动失败|麦克风|不支持|语音识别/i.test(res.error)
    if (soft) {
      voiceMicPausedByUser.value = true
      voiceState.value = 'idle'
      voiceReport.value = ''
      voiceChatPhase.value = 'idle'
      voiceMicFallbackHint.value = '语音没接上，先打字也能继续聊；点右下角 ▶ 再试麦克风。'
      return
    }
    voiceError.value = res.error
  }
}
async function stopVoiceRecognition() {
  return voiceChat.stopListening()
}
function ensureVoiceListening() {
  if (wbSidebar.activeMode !== 'voice') return
  voiceChat.ensureListening()
}
function interruptVoice() {
  cancelSpeculativeVoiceTurn()
  voiceChat.interruptCapture()
  __wbState.voiceStreamHandle?.abort()
  __wbState.voiceStreamHandle = null
  streamingTts.stop()
  voiceChatPhase.value = 'idle'
  voiceState.value = 'idle'
  voiceReport.value = ''
}

  return {
    ...ctx, resumeVoiceListeningInSayMode, enablePlatformChatMode, disablePlatformChatMode, togglePlatformChatMode,
    exitMakeToolbarToCasualChat, switchMakeIntent, drawWaveform, voiceAsrActiveId, voiceAsrBackendLabel,
    voiceDockDraft, showVoiceWaveform, voiceAsrConnecting, voiceAsrListening, voiceDockRecognizing,
    onVoiceDockSend, onVoiceMicToggle, resumeVoiceMic, forcePauseVoiceSession, resetVoiceListenSession,
    resetVoiceCaptureUi, finishContinuousUtterance, activateVoiceContinuous, voiceOrbMode, voiceOrbHint,
    voiceOrbActive, voiceStatusText, isGearAxisLocked, newConversationHandler, resetVoiceSession,
    onOrbClick, speakTextAndListen, _toggleVoiceListening, stopVoiceAsr, _onVoiceAsrError,
    startVoiceRecognition, stopVoiceRecognition, ensureVoiceListening, interruptVoice,
  }
}

export type useWbDrawWaveformBinds = ReturnType<typeof useWbDrawWaveform>

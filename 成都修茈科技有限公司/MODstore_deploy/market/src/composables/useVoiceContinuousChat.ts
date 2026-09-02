// 兼容 façade：useVoiceContinuousChat 已按关注点拆分（端点配置/推测式判定/ASR 恢复），
// 本文件保留原导出面（常量、类型与组合函数），内部编排与原单体行为完全一致。
import { ref } from 'vue'
import type { ASRResult } from './asr/types'
import { mergeAsrLiveText } from './mergeAsrLiveText'
import { normalizeVoiceAsrText } from './normalizeVoiceAsrText'
import { shouldFlushVoiceUtterance, type VoiceCaptureSnapshot } from './voiceEndpointLogic'
import { speculativeTextsMatch } from './voiceSpeculativeMatch'
import { takeMicPreflight } from './asr/micPreflight'
import {
  createVoiceEndpointResolver,
  refreshVoiceEndpoint,
  VOICE_ENDPOINT,
  type VoiceContinuousChatDeps,
} from './voiceContinuousChatConfig'
import { createVoiceSpeculation } from './voiceSpeculation'
import { createVoiceAsrRecovery } from './voiceAsrRecovery'

export { VOICE_ENDPOINT, VOICE_PHONE_ENDPOINT, voiceEndpointForDevice, refreshVoiceEndpoint } from './voiceContinuousChatConfig'
export type { VoiceContinuousChatDeps } from './voiceContinuousChatConfig'

export function useVoiceContinuousChat(deps: VoiceContinuousChatDeps) {
  const endpoint = createVoiceEndpointResolver(deps)

  const voiceDraft = ref('')
  const voiceTranscript = ref('')
  const voiceLivePreview = ref('')
  const voiceListening = ref(false)
  const voiceAudioLevel = ref(0)
  const micPausedByUser = ref(false)

  let continuousSilenceTimer: ReturnType<typeof setTimeout> | null = null
  let silenceWatchdog: ReturnType<typeof setInterval> | null = null
  let submitLock = false
  let hadSpeech = false
  let audioSpeaking = false
  let lastAsrAt = 0
  let lastAsrContentChangeAt = 0
  let lastSpeechAt = 0
  let lastSubmittedText = ''
  let lastSubmittedAt = 0
  let listenPartial = ''
  let _starting = false
  let micPeakLevel = 0
  let micWatchdog: ReturnType<typeof setTimeout> | null = null
  let serverFinalTimer: ReturnType<typeof setTimeout> | null = null

  const spec = createVoiceSpeculation({
    d: deps,
    endpoint,
    micPausedByUser,
    voiceTranscript,
    voiceLivePreview,
    voiceListening,
    getSubmitLock: () => submitLock,
    shouldFlushUtterance,
    finishUtterance,
  })
  const {
    isSpeculating,
    partialStable,
    cancelSpeculativeState,
    clearPartialStableTimer,
    clearS2sPartialTimer,
    scheduleS2sPartialStart,
    scheduleSpeculativeCheck,
  } = spec

  const asrRecovery = createVoiceAsrRecovery({
    d: deps,
    voiceTranscript,
    voiceDraft,
    voiceLivePreview,
    voiceListening,
    voiceAudioLevel,
    micPausedByUser,
    finishUtterance,
    stopAsr,
    stopSilenceWatchdog,
    clearContinuousSilenceTimer,
    resetCaptureUi,
    cancelSpeculativeState,
    startListening,
  })
  const { clearWebSpeechStallTimer, scheduleWebSpeechStallCheck, onAsrError } = asrRecovery

  function clearContinuousSilenceTimer() {
    if (continuousSilenceTimer) {
      clearTimeout(continuousSilenceTimer)
      continuousSilenceTimer = null
    }
  }

  function clearServerFinalTimer() {
    if (serverFinalTimer) {
      clearTimeout(serverFinalTimer)
      serverFinalTimer = null
    }
  }

  function resetCaptureState() {
    hadSpeech = false
    audioSpeaking = false
    lastAsrAt = 0
    lastAsrContentChangeAt = 0
    lastSpeechAt = 0
    clearContinuousSilenceTimer()
    clearPartialStableTimer()
    clearServerFinalTimer()
    clearS2sPartialTimer()
    spec.clearActiveS2sTurn()
  }

  function captureSnapshot(): VoiceCaptureSnapshot {
    return {
      audioSpeaking,
      lastSpeechAt,
      lastAsrContentChangeAt,
      lastAsrAt,
      hadSpeech,
      listenPartial,
      voiceTranscript: voiceTranscript.value,
      voiceDraft: voiceDraft.value,
      lastSubmittedText,
      lastSubmittedAt,
    }
  }

  function shouldFlushUtterance(): boolean {
    return shouldFlushVoiceUtterance(captureSnapshot(), endpoint(), Date.now())
  }

  function scheduleServerFinalFlush() {
    clearServerFinalTimer()
    const debounce = endpoint().serverFinalDebounceMs ?? VOICE_ENDPOINT.serverFinalDebounceMs
    serverFinalTimer = setTimeout(() => {
      serverFinalTimer = null
      if (!deps.autoSend.value || submitLock || micPausedByUser.value) return
      if (audioSpeaking) return
      const pending = listenPartial.trim() || voiceTranscript.value.trim() || voiceDraft.value.trim()
      if (!pending) return
      // FunASR offline 段已结束：信任服务端断句，不受 partialMinChars 限制
      void finishUtterance()
    }, debounce)
  }

  function shouldTrustAsrFinal(r: ASRResult): boolean {
    if (deps.getAsrBackendId?.() === 'funasr') {
      return r.segmentMode === 'offline'
    }
    return !!r.isFinal
  }

  function shouldIgnoreAsrText(text: string, isFinal = false): boolean {
    const t = text.trim()
    if (!t) return true
    if (t === lastSubmittedText) return true
    if (!isFinal && t === listenPartial) return true
    return false
  }

  function hasFreshCapture(text: string): boolean {
    const t = text.trim()
    if (!t) return false
    if (t !== lastSubmittedText) return true
    return lastAsrAt > lastSubmittedAt
  }

  function shouldSkipAutoSubmit(text: string): boolean {
    return !hasFreshCapture(text)
  }

  function noteSubmitted(text: string) {
    lastSubmittedText = text.trim()
    lastSubmittedAt = Date.now()
    voiceDraft.value = ''
    voiceTranscript.value = ''
    voiceLivePreview.value = ''
    listenPartial = ''
    resetCaptureState()
    cancelSpeculativeState()
  }

  function stopSilenceWatchdog() {
    if (silenceWatchdog) {
      clearInterval(silenceWatchdog)
      silenceWatchdog = null
    }
  }

  function startSilenceWatchdog() {
    stopSilenceWatchdog()
    silenceWatchdog = setInterval(() => {
      if (!deps.autoSend.value || !voiceListening.value || submitLock) return
      if (micPausedByUser.value) return
      if (shouldFlushUtterance()) void finishUtterance()
    }, 150)
  }

  function scheduleContinuousSilenceSubmit() {
    if (!deps.autoSend.value || submitLock) return
    if (!voiceListening.value && !hadSpeech) return
    clearContinuousSilenceTimer()
    continuousSilenceTimer = setTimeout(() => {
      continuousSilenceTimer = null
      if (shouldFlushUtterance()) {
        void finishUtterance()
        return
      }
      const pending = listenPartial.trim() || voiceTranscript.value.trim() || voiceDraft.value.trim()
      if (voiceListening.value && pending && deps.autoSend.value) {
        scheduleContinuousSilenceSubmit()
      }
    }, endpoint().silenceMs)
  }

  function markAsrActivity(contentChanged: boolean) {
    const now = Date.now()
    lastAsrAt = now
    lastSpeechAt = now
    if (contentChanged) lastAsrContentChangeAt = lastAsrAt
    hadSpeech = true
  }

  function handleAsrResult(r: ASRResult) {
    if (micPausedByUser.value) return
    if (r.text?.trim()) clearWebSpeechStallTimer()
    const trimmed = r.text?.trim() || ''
    if (trimmed && shouldIgnoreAsrText(trimmed, !!r.isFinal)) return

    if (r.text) {
      const prevListen = listenPartial
      const contentChanged = trimmed !== prevListen
      if (contentChanged && isSpeculating.value) {
        cancelSpeculativeState()
      }
      const merged = normalizeVoiceAsrText(mergeAsrLiveText(prevListen, trimmed, !!r.isFinal))
      listenPartial = merged
      markAsrActivity(merged !== prevListen)
      voiceTranscript.value = merged
      voiceLivePreview.value = merged
      if (merged !== prevListen && merged) {
        scheduleSpeculativeCheck(merged)
        scheduleS2sPartialStart(merged)
      }
      if (deps.autoSend.value && deps.isChatBusy?.()) {
        if (deps.isTtsPlaying?.()) {
          /* 由 onAsrDuringTts / 音频电平触发真打断 */
        } else if (audioSpeaking) {
          deps.onBargeIn()
        }
      }
    }

    if (!deps.autoSend.value || submitLock) return
    if (r.isFinal && trimmed && shouldTrustAsrFinal(r)) {
      if (deps.getAsrBackendId?.() === 'funasr') {
        const finalText = normalizeVoiceAsrText(trimmed)
        const phone = deps.voiceUsePhonePipeline?.() ?? deps.voiceUseS2S?.()
        if (phone && deps.onS2SUtteranceFinalize && spec.getActiveS2sTurn()) {
          deps.onS2SUtteranceFinalize(finalText, spec.getActiveS2sTurn())
        }
        scheduleServerFinalFlush()
      } else {
        void finishUtterance()
      }
      return
    }
    if (trimmed) {
      scheduleContinuousSilenceSubmit()
    }
  }

  function handleAudioLevel(level: number) {
    voiceAudioLevel.value = level
    if (level > micPeakLevel) micPeakLevel = level
    if (deps.autoSend.value && deps.isChatBusy?.() && deps.isTtsPlaying?.() && deps.onAsrDuringTts?.(level)) {
      return
    }
    if (!deps.autoSend.value || submitLock || !voiceListening.value || micPausedByUser.value) return
    const ep = endpoint()
    const speaking = level >= ep.speechLevel
    if (speaking) {
      hadSpeech = true
      audioSpeaking = true
      lastSpeechAt = Date.now()
      clearContinuousSilenceTimer()
      clearServerFinalTimer()
      if (isSpeculating.value) cancelSpeculativeState()
      return
    }
    // 声纹由有频变平：从说话进入停顿，启动发送倒计时
    if (audioSpeaking) {
      audioSpeaking = false
      lastSpeechAt = Date.now()
      if (deps.getAsrBackendId?.() === 'funasr') {
        deps.signalAsrEndOfSpeech?.()
      }
    }
    const hasPartial = Boolean(listenPartial.trim() || voiceTranscript.value.trim())
    if (hasPartial || hadSpeech) {
      scheduleContinuousSilenceSubmit()
    }
  }

  async function flushAsr(): Promise<string> {
    if (!deps.isVoiceTargetActive()) return ''
    return (await deps.asr.flushListening()).trim()
  }

  async function finishUtterance() {
    if (submitLock || !deps.autoSend.value || micPausedByUser.value) return
    clearContinuousSilenceTimer()
    submitLock = true
    try {
      let text = normalizeVoiceAsrText(voiceTranscript.value.trim() || voiceDraft.value.trim())
      if (voiceListening.value && deps.isVoiceTargetActive()) {
        try {
          const flushed = normalizeVoiceAsrText((await flushAsr()).trim())
          if (flushed) {
            if (deps.getAsrBackendId?.() === 'funasr') {
              text = flushed.length >= text.length ? flushed : normalizeVoiceAsrText(mergeAsrLiveText(text, flushed, true))
            } else {
              text = flushed
            }
          }
        } catch {
          /* keep partial */
        }
        resetCaptureState()
        if (!voiceListening.value) {
          deps.voiceState.value = 'listening'
          voiceListening.value = true
        }
      }
      if (!text) return
      if (shouldSkipAutoSubmit(text)) return

      const specPartial = spec.getSpeculativePartialText()
      const specActive = isSpeculating.value && specPartial

      if (specActive && speculativeTextsMatch(text, specPartial)) {
        isSpeculating.value = false
        spec.setSpeculativePartialText(null)
        partialStable.value = false
        lastSubmittedText = text.trim()
        lastSubmittedAt = Date.now()
        voiceDraft.value = ''
        voiceTranscript.value = ''
        voiceLivePreview.value = ''
        listenPartial = ''
        await deps.onUtteranceReady(text, { speculativePartial: specPartial })
        return
      }

      if (specActive) {
        cancelSpeculativeState()
      }

      lastSubmittedText = text.trim()
      lastSubmittedAt = Date.now()
      voiceDraft.value = ''
      voiceTranscript.value = ''
      voiceLivePreview.value = ''
      listenPartial = ''
      resetCaptureState()
      await deps.onUtteranceReady(text, { speculativePartial: null })
    } finally {
      submitLock = false
    }
  }

  function resetListenSession() {
    listenPartial = ''
    resetCaptureState()
  }

  function clearMicWatchdog() {
    if (micWatchdog) {
      clearTimeout(micWatchdog)
      micWatchdog = null
    }
  }

  function startMicWatchdog() {
    clearMicWatchdog()
    micPeakLevel = 0
    micWatchdog = setTimeout(() => {
      micWatchdog = null
      if (!voiceListening.value || micPausedByUser.value || submitLock) return
      const hasText = Boolean(listenPartial.trim() || voiceTranscript.value.trim() || voiceDraft.value.trim())
      if (hasText) return
      if (micPeakLevel >= 0.008) return
      if (deps.isAsrReady && !deps.isAsrReady()) {
        void onAsrError('语音服务未就绪，正在重连…')
        return
      }
      void onAsrError('未检测到麦克风信号，请点右下角麦克风重试并允许权限。')
    }, 3500)
  }

  function resetCaptureUi() {
    clearMicWatchdog()
    clearContinuousSilenceTimer()
    stopSilenceWatchdog()
    resetCaptureState()
    cancelSpeculativeState()
    if (deps.isVoiceTargetActive()) {
      deps.asr.abort()
      deps.clearVoiceTarget()
    }
    voiceListening.value = false
    voiceAudioLevel.value = 0
    deps.voiceState.value = 'idle'
  }

  async function startListening(opts?: { fresh?: boolean; reconnect?: boolean }) {
    if (submitLock || _starting) return
    if (micPausedByUser.value && opts?.fresh !== false) return
    if (voiceListening.value && deps.isVoiceTargetActive() && opts?.fresh === false && !opts?.reconnect) {
      startSilenceWatchdog()
      return
    }
    if (!localStorage.getItem('modstore_token')) {
      resetCaptureUi()
      return { error: '请先登录后再使用语音识别。' as const }
    }

    _starting = true
    try {
      deps.beforeStartListening?.()
      refreshVoiceEndpoint()
      clearContinuousSilenceTimer()
      const fresh = opts?.fresh !== false
      if (fresh) {
        micPausedByUser.value = false
        resetListenSession()
        voiceDraft.value = ''
        voiceTranscript.value = ''
      }
      deps.voiceChatPhase.value = 'listening'
      deps.setVoiceTarget()
      const micPreflight = takeMicPreflight()

      await deps.asr.startListening(
        (r) => handleAsrResult(r),
        (msg) => onAsrError(msg),
        (level) => handleAudioLevel(level),
        {
          continuous: true,
          mediaStream: micPreflight ?? undefined,
        },
      )

      if (deps.asr.sessionReady.value) {
        voiceListening.value = true
        deps.voiceState.value = 'listening'
        startSilenceWatchdog()
        startMicWatchdog()
        scheduleWebSpeechStallCheck()
        return { error: null as string | null }
      }

      const err = deps.asr.error.value || '语音识别启动失败，请点麦克风重试。'
      resetCaptureUi()
      return { error: err as string }
    } finally {
      _starting = false
    }
  }

  async function stopAsr(): Promise<string> {
    if (!deps.isVoiceTargetActive()) return ''
    const text = await deps.asr.stopListening()
    deps.clearVoiceTarget()
    return text
  }

  async function stopListening() {
    stopSilenceWatchdog()
    const text = await stopAsr()
    voiceListening.value = false
    voiceAudioLevel.value = 0
    hadSpeech = false
    if (deps.voiceState.value === 'listening') {
      deps.voiceState.value = 'idle'
    }
    const trimmed = text.trim()
    if (trimmed) voiceTranscript.value = trimmed
    return text
  }

  function ensureListening() {
    if (micPausedByUser.value) return
    if (submitLock) return
    if (!localStorage.getItem('modstore_token')) return
    const asrReady = deps.isAsrReady?.() ?? deps.asr.sessionReady.value
    if (voiceListening.value && asrReady) {
      const pending = voiceTranscript.value.trim() || voiceDraft.value.trim()
      if (pending && hasFreshCapture(pending)) {
        scheduleContinuousSilenceSubmit()
      }
      return
    }
    void startListening({ fresh: !voiceListening.value, reconnect: voiceListening.value })
  }

  function interruptCapture() {
    clearContinuousSilenceTimer()
    stopSilenceWatchdog()
    hadSpeech = false
    cancelSpeculativeState()
    if (deps.isVoiceTargetActive()) {
      deps.asr.abort({ keepMic: true })
      deps.clearVoiceTarget()
    }
    voiceListening.value = false
  }

  return {
    voiceDraft,
    voiceTranscript,
    voiceLivePreview,
    voiceListening,
    voiceAudioLevel,
    micPausedByUser,
    isSpeculating,
    partialStable,
    clearContinuousSilenceTimer,
    stopSilenceWatchdog,
    resetListenSession,
    resetCaptureUi,
    noteSubmitted,
    hasFreshCapture,
    startListening,
    stopListening,
    stopAsr,
    finishUtterance,
    ensureListening,
    interruptCapture,
    onAsrError,
    getSubmitLock: () => submitLock,
  }
}

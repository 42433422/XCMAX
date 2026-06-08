import { ref, onMounted, onBeforeUnmount, type Ref } from 'vue'
import type { ASRResult } from './asr/types'
import type { useSpeechRecognition } from './useSpeechRecognition'
import { mergeAsrLiveText } from './mergeAsrLiveText'
import { normalizeVoiceAsrText } from './normalizeVoiceAsrText'
import {
  shouldFlushVoiceUtterance,
  type VoiceCaptureSnapshot,
} from './voiceEndpointLogic'
import { speculativeTextsMatch } from './voiceSpeculativeMatch'
import { takeMicPreflight } from './asr/micPreflight'
import { wakeSharedMicCapture } from './asr/sharedMicCapture'
import { isIOSVoiceDevice, isMobileVoiceDevice } from './voiceDevice'

export const VOICE_ENDPOINT = {
  /** 说完后的静音窗口：桌面约 700ms；过短易切碎句 */
  silenceMs: 700,
  speechLevel: 0.012,
  /** 推测式 LLM 需 partial 稳定更久，避免半句就「嗯，你说」 */
  partialStableMs: 1100,
  /** S2S：partial 稳定后发 utterance_start（早于 speculative） */
  partialStableS2sMs: 500,
  /** 中文短句常 <10 字；过低易半句误发，6 字可覆盖「听得到吗」类问句 */
  partialMinChars: 6,
  /** FunASR offline 段确认后的提交防抖 */
  serverFinalDebounceMs: 280,
} as const

/** unified / s2s 电话式：更短判停、更早开答（对标豆包动态判停） */
export const VOICE_PHONE_ENDPOINT = {
  silenceMs: 520,
  speechLevel: 0.011,
  partialStableMs: 950,
  partialStableS2sMs: 380,
  partialMinChars: 4,
  serverFinalDebounceMs: 220,
} as const

export function voiceEndpointForDevice() {
  if (!isMobileVoiceDevice()) return VOICE_ENDPOINT
  const ios = isIOSVoiceDevice()
  return {
    silenceMs: ios ? 900 : 1000,
    speechLevel: ios ? 0.028 : 0.024,
    partialStableMs: ios ? 1200 : 1300,
    partialStableS2sMs: ios ? 550 : 600,
    partialMinChars: VOICE_ENDPOINT.partialMinChars,
    serverFinalDebounceMs: VOICE_ENDPOINT.serverFinalDebounceMs,
  } as const
}

let activeEndpoint = voiceEndpointForDevice()

export function refreshVoiceEndpoint() {
  activeEndpoint = voiceEndpointForDevice()
}

export interface VoiceContinuousChatDeps {
  asr: ReturnType<typeof useSpeechRecognition>
  isAsrReady?: () => boolean
  autoSend: Ref<boolean>
  voiceState: Ref<string>
  voiceChatPhase: Ref<string>
  isVoiceTargetActive: () => boolean
  setVoiceTarget: () => void
  clearVoiceTarget: () => void
  beforeStartListening?: () => void
  onUtteranceReady: (text: string, ctx: { speculativePartial: string | null }) => Promise<void>
  onSpeculativeStart: (partialText: string) => void
  onSpeculativeCancel: () => void
  onBargeIn: () => void
  /** TTS 正在合成/播放时为 true */
  isTtsPlaying?: () => boolean
  /** TTS 播放中检测到用户说话；返回 true 表示已触发打断 */
  onAsrDuringTts?: (level: number) => boolean
  canSpeculate: (partialText: string) => boolean
  isChatBusy: () => boolean
  getAsrBackendId?: () => string
  /** FunASR：用户停说时立即通知服务端（is_speaking:false） */
  signalAsrEndOfSpeech?: () => void
  /** unified/s2s：partial 稳定后提前开 LLM（不等 offline） */
  onS2SPartialStable?: (text: string, turnId: string) => void
  /** unified/s2s：offline 到达后 finalize / 纠错 */
  onS2SUtteranceFinalize?: (text: string, turnId: string) => void
  /** unified 或 s2s 电话式管线 */
  voiceUsePhonePipeline?: () => boolean
  /** @deprecated 使用 voiceUsePhonePipeline */
  voiceUseS2S?: () => boolean
  /** 电话式：更短判停与更早 provisional */
  usePhoneLatency?: () => boolean
}

export function useVoiceContinuousChat(deps: VoiceContinuousChatDeps) {
  function endpoint() {
    if (deps.usePhoneLatency?.()) {
      const base = activeEndpoint
      return {
        ...base,
        silenceMs: Math.min(base.silenceMs, VOICE_PHONE_ENDPOINT.silenceMs),
        partialStableS2sMs: Math.min(
          base.partialStableS2sMs ?? VOICE_ENDPOINT.partialStableS2sMs,
          VOICE_PHONE_ENDPOINT.partialStableS2sMs,
        ),
        partialMinChars: Math.min(base.partialMinChars, VOICE_PHONE_ENDPOINT.partialMinChars),
        serverFinalDebounceMs: Math.min(
          base.serverFinalDebounceMs ?? VOICE_ENDPOINT.serverFinalDebounceMs,
          VOICE_PHONE_ENDPOINT.serverFinalDebounceMs,
        ),
        speechLevel: Math.min(base.speechLevel, VOICE_PHONE_ENDPOINT.speechLevel),
      }
    }
    return activeEndpoint
  }

  const voiceDraft = ref('')
  const voiceTranscript = ref('')
  const voiceLivePreview = ref('')
  const voiceListening = ref(false)
  const voiceAudioLevel = ref(0)
  const micPausedByUser = ref(false)
  const isSpeculating = ref(false)
  const partialStable = ref(false)

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
  let speculativePartialText: string | null = null
  let partialStableTimer: ReturnType<typeof setTimeout> | null = null
  let partialStableSince = 0
  let webSpeechStallTimer: ReturnType<typeof setTimeout> | null = null
  let lastWebSpeechRetryAt = 0
  let _starting = false
  let micPeakLevel = 0
  let micWatchdog: ReturnType<typeof setTimeout> | null = null
  let serverFinalTimer: ReturnType<typeof setTimeout> | null = null
  let s2sPartialTimer: ReturnType<typeof setTimeout> | null = null
  let s2sPartialStableSince = 0
  let activeS2sTurnId = ''
  let s2sTurnSeq = 0

  function clearContinuousSilenceTimer() {
    if (continuousSilenceTimer) {
      clearTimeout(continuousSilenceTimer)
      continuousSilenceTimer = null
    }
  }

  function clearWebSpeechStallTimer() {
    if (webSpeechStallTimer) {
      clearTimeout(webSpeechStallTimer)
      webSpeechStallTimer = null
    }
  }

  function scheduleWebSpeechStallCheck() {
    clearWebSpeechStallTimer()
    if (!voiceListening.value || micPausedByUser.value) return
    if (deps.getAsrBackendId?.() !== 'funasr') return
    webSpeechStallTimer = setTimeout(() => {
      webSpeechStallTimer = null
      if (!voiceListening.value || micPausedByUser.value) return
      if (deps.getAsrBackendId?.() !== 'funasr') return
      if (voiceTranscript.value.trim() || voiceLivePreview.value.trim()) return
      const now = Date.now()
      if (now - lastWebSpeechRetryAt < 8000) return
      lastWebSpeechRetryAt = now
      reconnectAsrKeepUi()
      void startListening({ fresh: false, reconnect: true })
    }, 12000)
  }

  function clearServerFinalTimer() {
    if (serverFinalTimer) {
      clearTimeout(serverFinalTimer)
      serverFinalTimer = null
    }
  }

  function clearS2sPartialTimer() {
    if (s2sPartialTimer) {
      clearTimeout(s2sPartialTimer)
      s2sPartialTimer = null
    }
    s2sPartialStableSince = 0
  }

  function nextS2sTurnId(): string {
    s2sTurnSeq += 1
    return `v${Date.now()}-${s2sTurnSeq}`
  }

  function scheduleS2sPartialStart(partialText: string) {
    clearS2sPartialTimer()
    const phone = deps.voiceUsePhonePipeline?.() ?? deps.voiceUseS2S?.()
    if (!phone || !deps.onS2SPartialStable) return
    if (!deps.autoSend.value || submitLock || micPausedByUser.value) return
    if (partialText.length < endpoint().partialMinChars) return
    if (deps.isChatBusy?.() && !isSpeculating.value) return

    const turnId = nextS2sTurnId()
    activeS2sTurnId = turnId
    s2sPartialStableSince = Date.now()
    const stableMs = endpoint().partialStableS2sMs ?? VOICE_ENDPOINT.partialStableS2sMs
    s2sPartialTimer = setTimeout(() => {
      s2sPartialTimer = null
      const current = voiceTranscript.value.trim() || voiceLivePreview.value.trim()
      if (current !== partialText) return
      if (Date.now() - s2sPartialStableSince < stableMs - 40) return
      if (activeS2sTurnId !== turnId) return
      deps.onS2SPartialStable?.(current, turnId)
    }, stableMs)
  }

  function clearPartialStableTimer() {
    if (partialStableTimer) {
      clearTimeout(partialStableTimer)
      partialStableTimer = null
    }
    partialStable.value = false
    partialStableSince = 0
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
    activeS2sTurnId = ''
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
      const pending =
        listenPartial.trim() ||
        voiceTranscript.value.trim() ||
        voiceDraft.value.trim()
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

  function cancelSpeculativeState() {
    clearPartialStableTimer()
    if (isSpeculating.value || speculativePartialText) {
      isSpeculating.value = false
      speculativePartialText = null
      deps.onSpeculativeCancel()
    }
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
      const pending =
        listenPartial.trim() ||
        voiceTranscript.value.trim() ||
        voiceDraft.value.trim()
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

  function scheduleSpeculativeCheck(partialText: string) {
    clearPartialStableTimer()
    if (!deps.canSpeculate(partialText)) return
    if (deps.isChatBusy() && !isSpeculating.value) return
    if (partialText.length < endpoint().partialMinChars) return

    partialStableSince = Date.now()
    partialStableTimer = setTimeout(() => {
      partialStableTimer = null
      const current = voiceTranscript.value.trim() || voiceLivePreview.value.trim()
      if (current !== partialText) return
      if (Date.now() - partialStableSince < endpoint().partialStableMs - 50) return
      if (deps.autoSend.value && !submitLock && voiceListening.value && shouldFlushUtterance()) {
        void finishUtterance()
        return
      }
      if (deps.isChatBusy() && !isSpeculating.value) return
      if (!deps.canSpeculate(current)) return
      if (isSpeculating.value && speculativePartialText === current) return

      partialStable.value = true
      isSpeculating.value = true
      speculativePartialText = current
      deps.onSpeculativeStart(current)
    }, endpoint().partialStableMs)
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
      const merged = normalizeVoiceAsrText(
        mergeAsrLiveText(prevListen, trimmed, !!r.isFinal),
      )
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
        if (phone && deps.onS2SUtteranceFinalize && activeS2sTurnId) {
          deps.onS2SUtteranceFinalize(finalText, activeS2sTurnId)
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
    if (
      deps.autoSend.value &&
      deps.isChatBusy?.() &&
      deps.isTtsPlaying?.() &&
      deps.onAsrDuringTts?.(level)
    ) {
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
      let text = normalizeVoiceAsrText(
        voiceTranscript.value.trim() || voiceDraft.value.trim(),
      )
      if (voiceListening.value && deps.isVoiceTargetActive()) {
        try {
          const flushed = normalizeVoiceAsrText((await flushAsr()).trim())
          if (flushed) {
            if (deps.getAsrBackendId?.() === 'funasr') {
              text =
                flushed.length >= text.length
                  ? flushed
                  : normalizeVoiceAsrText(mergeAsrLiveText(text, flushed, true))
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

      const specPartial = speculativePartialText
      const specActive = isSpeculating.value && specPartial

      if (specActive && speculativeTextsMatch(text, specPartial)) {
        isSpeculating.value = false
        speculativePartialText = null
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
      const hasText = Boolean(
        listenPartial.trim() || voiceTranscript.value.trim() || voiceDraft.value.trim(),
      )
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
    if (
      voiceListening.value &&
      deps.isVoiceTargetActive() &&
      opts?.fresh === false &&
      !opts?.reconnect
    ) {
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

  function onAsrError(msg: string) {
    const hasText = Boolean(voiceTranscript.value.trim() || voiceDraft.value.trim())
    if (hasText && voiceListening.value && deps.autoSend.value) {
      void finishUtterance()
      return
    }
    if (hasText && voiceListening.value) {
      voiceListening.value = false
      stopSilenceWatchdog()
      deps.voiceState.value = 'idle'
      void stopAsr()
      return { msg, retry: false }
    }
    const whisperOnly = msg.includes('Whisper') || msg.includes('模型')
    const noRetry =
      msg.includes('不支持') ||
      msg.includes('权限') ||
      msg.includes('未找到') ||
      msg.includes('请先登录')
    const retry = deps.autoSend.value && !noRetry && !whisperOnly

    if (deps.autoSend.value && whisperOnly) {
      reconnectAsrKeepUi()
      return { msg: '', retry: true, delayMs: 400, fresh: true }
    }
    if (retry) {
      reconnectAsrKeepUi()
      return { msg, retry: true, delayMs: 400, fresh: !hasText }
    }
    resetCaptureUi()
    return { msg, retry: false }
  }

  /** ASR 降级/重连：保持场景状态，但不假装已在收音（避免声纹死线） */
  function reconnectAsrKeepUi() {
    clearContinuousSilenceTimer()
    stopSilenceWatchdog()
    cancelSpeculativeState()
    voiceAudioLevel.value = 0
    if (deps.isVoiceTargetActive()) {
      deps.asr.abort({ keepMic: true })
    }
    voiceListening.value = false
    if (deps.voiceState.value === 'idle') deps.voiceState.value = 'listening'
    if (deps.voiceChatPhase.value === 'idle') deps.voiceChatPhase.value = 'listening'
  }

  function wakeMicIfListening() {
    if (voiceListening.value || deps.isVoiceTargetActive()) {
      wakeSharedMicCapture()
    }
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', onMicVisibility)
    document.addEventListener('pointerdown', wakeMicIfListening, true)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('visibilitychange', onMicVisibility)
    document.removeEventListener('pointerdown', wakeMicIfListening, true)
  })

  function onMicVisibility() {
    if (document.visibilityState === 'visible') wakeMicIfListening()
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

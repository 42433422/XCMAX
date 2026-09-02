// ASR 恢复与生命周期：错误分支、静默重连、麦克风唤醒与组件挂载监听（自 useVoiceContinuousChat 原样迁移）。
import { onBeforeUnmount, onMounted } from 'vue'
import type { Ref } from 'vue'
import { wakeSharedMicCapture } from './asr/sharedMicCapture'
import type { VoiceContinuousChatDeps } from './voiceContinuousChatConfig'

export interface VoiceAsrRecoveryDeps {
  /** useVoiceContinuousChat 的原始 deps */
  d: VoiceContinuousChatDeps
  voiceTranscript: Ref<string>
  voiceDraft: Ref<string>
  voiceLivePreview: Ref<string>
  voiceListening: Ref<boolean>
  voiceAudioLevel: Ref<number>
  micPausedByUser: Ref<boolean>
  finishUtterance: () => Promise<void>
  stopAsr: () => Promise<string>
  stopSilenceWatchdog: () => void
  clearContinuousSilenceTimer: () => void
  resetCaptureUi: () => void
  cancelSpeculativeState: () => void
  startListening: (opts?: { fresh?: boolean; reconnect?: boolean }) => Promise<unknown>
}

export function createVoiceAsrRecovery(arg: VoiceAsrRecoveryDeps) {
  const {
    d,
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
  } = arg

  let webSpeechStallTimer: ReturnType<typeof setTimeout> | null = null
  let lastWebSpeechRetryAt = 0

  function clearWebSpeechStallTimer() {
    if (webSpeechStallTimer) {
      clearTimeout(webSpeechStallTimer)
      webSpeechStallTimer = null
    }
  }

  function scheduleWebSpeechStallCheck() {
    clearWebSpeechStallTimer()
    if (!voiceListening.value || micPausedByUser.value) return
    if (d.getAsrBackendId?.() !== 'funasr') return
    webSpeechStallTimer = setTimeout(() => {
      webSpeechStallTimer = null
      if (!voiceListening.value || micPausedByUser.value) return
      if (d.getAsrBackendId?.() !== 'funasr') return
      if (voiceTranscript.value.trim() || voiceLivePreview.value.trim()) return
      const now = Date.now()
      if (now - lastWebSpeechRetryAt < 8000) return
      lastWebSpeechRetryAt = now
      reconnectAsrKeepUi()
      void startListening({ fresh: false, reconnect: true })
    }, 12000)
  }

  function onAsrError(msg: string) {
    const hasText = Boolean(voiceTranscript.value.trim() || voiceDraft.value.trim())
    if (hasText && voiceListening.value && d.autoSend.value) {
      void finishUtterance()
      return
    }
    if (hasText && voiceListening.value) {
      voiceListening.value = false
      stopSilenceWatchdog()
      d.voiceState.value = 'idle'
      void stopAsr()
      return { msg, retry: false }
    }
    const whisperOnly = msg.includes('Whisper') || msg.includes('模型')
    const noRetry = msg.includes('不支持') || msg.includes('权限') || msg.includes('未找到') || msg.includes('请先登录')
    const retry = d.autoSend.value && !noRetry && !whisperOnly

    if (d.autoSend.value && whisperOnly) {
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
    if (d.isVoiceTargetActive()) {
      d.asr.abort({ keepMic: true })
    }
    voiceListening.value = false
    if (d.voiceState.value === 'idle') d.voiceState.value = 'listening'
    if (d.voiceChatPhase.value === 'idle') d.voiceChatPhase.value = 'listening'
  }

  function wakeMicIfListening() {
    if (voiceListening.value || d.isVoiceTargetActive()) {
      wakeSharedMicCapture()
    }
  }

  function onMicVisibility() {
    if (document.visibilityState === 'visible') wakeMicIfListening()
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', onMicVisibility)
    document.addEventListener('pointerdown', wakeMicIfListening, true)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('visibilitychange', onMicVisibility)
    document.removeEventListener('pointerdown', wakeMicIfListening, true)
  })

  return {
    clearWebSpeechStallTimer,
    scheduleWebSpeechStallCheck,
    reconnectAsrKeepUi,
    onAsrError,
  }
}

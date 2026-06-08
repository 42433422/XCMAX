import { ref, onBeforeUnmount } from 'vue'
import { useSpeechRecognition } from '../useSpeechRecognition'
import type { ASRResult } from '../asr/types'
import { FunASRBackend } from '../asr/FunASRBackend'
import { WebSpeechBackend } from '../asr/WebSpeechBackend'
import { useStreamingTts, ttsConfigFromPersonalSettings } from '../useStreamingTts'
import { loadPersonalSettings } from '../../utils/personalSettings'

export type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking'

function voiceInputSupported(): boolean {
  if (typeof window === 'undefined') return false
  try {
    if (new FunASRBackend().isAvailable()) return true
    if (new WebSpeechBackend().isAvailable()) return true
  } catch {
    // ignore probe errors
  }
  return Boolean(navigator.mediaDevices?.getUserMedia)
}

export function useVoiceInput(onFinalText: (text: string) => Promise<void>) {
  const state = ref<VoiceState>('idle')
  const error = ref('')
  const isSpeaking = ref(false)
  const muted = ref(false)
  const rate = ref(1.0)
  let submitLock = false

  const streamingTts = useStreamingTts(() => {
    const ps = loadPersonalSettings()
    return ttsConfigFromPersonalSettings({ ...ps, ttsRate: rate.value })
  })

  const asr = useSpeechRecognition()
  const isSupported = voiceInputSupported()

  function speak(text: string): Promise<void> {
    if (muted.value || !text) return Promise.resolve()
    state.value = 'speaking'
    isSpeaking.value = true
    return streamingTts.speak(text).finally(() => {
      isSpeaking.value = false
      if (state.value === 'speaking') state.value = 'idle'
    })
  }

  async function submitRecognizedText(text: string, opts?: { emptyMessage?: string }) {
    const trimmed = text.trim()
    if (submitLock) return
    if (!trimmed) {
      if (state.value === 'listening') state.value = 'idle'
      if (opts?.emptyMessage) error.value = opts.emptyMessage
      return
    }
    submitLock = true
    error.value = ''
    state.value = 'thinking'
    try {
      await onFinalText(trimmed)
    } finally {
      submitLock = false
      if (state.value === 'thinking') state.value = 'idle'
    }
  }

  function startListening() {
    error.value = ''
    state.value = 'listening'
    asr.startListening(
      (r: ASRResult) => {
        if (r.isFinal) {
          void submitRecognizedText(r.text).finally(() => {
            asr.abort()
          })
        }
      },
      (msg: string) => {
        error.value = msg
        state.value = 'idle'
        asr.abort()
      },
    )
  }

  /** 用户点击停止：提交当前识别结果（与工作台 inline 语音一致） */
  async function stopListening() {
    if (state.value !== 'listening') return
    asr.signalEndOfSpeech()
    const text = (await asr.stopListening()).trim()
    if (submitLock) return
    await submitRecognizedText(text, {
      emptyMessage: '未识别到文字，请再试一次或使用文字输入。',
    })
  }

  function stopAll() {
    asr.abort()
    streamingTts.stop()
    isSpeaking.value = false
    state.value = 'idle'
  }

  function toggleMute() {
    muted.value = !muted.value
    if (muted.value) {
      streamingTts.stop()
      isSpeaking.value = false
    }
  }

  onBeforeUnmount(() => { stopAll() })

  return {
    state,
    error,
    isSpeaking,
    muted,
    rate,
    isSupported,
    interimText: asr.interimText,
    loadingHint: asr.loadingHint,
    sessionReady: asr.sessionReady,
    startListening,
    stopListening,
    stopAll,
    speak,
    toggleMute,
  }
}

// 推测式 LLM 与 S2S partial 稳定判定：speculative 状态机 + unified/s2s 提前开答（自 useVoiceContinuousChat 原样迁移）。
import { ref } from 'vue'
import type { Ref } from 'vue'
import { VOICE_ENDPOINT } from './voiceContinuousChatConfig'
import type { VoiceContinuousChatDeps, VoiceEndpointResolver } from './voiceContinuousChatConfig'

export interface VoiceSpeculationDeps {
  /** useVoiceContinuousChat 的原始 deps */
  d: VoiceContinuousChatDeps
  endpoint: VoiceEndpointResolver
  micPausedByUser: Ref<boolean>
  voiceTranscript: Ref<string>
  voiceLivePreview: Ref<string>
  voiceListening: Ref<boolean>
  getSubmitLock: () => boolean
  shouldFlushUtterance: () => boolean
  finishUtterance: () => Promise<void>
}

export function createVoiceSpeculation(arg: VoiceSpeculationDeps) {
  const {
    d,
    endpoint,
    micPausedByUser,
    voiceTranscript,
    voiceLivePreview,
    voiceListening,
    getSubmitLock,
    shouldFlushUtterance,
    finishUtterance,
  } = arg

  const isSpeculating = ref(false)
  const partialStable = ref(false)

  let speculativePartialText: string | null = null
  let partialStableTimer: ReturnType<typeof setTimeout> | null = null
  let partialStableSince = 0
  let s2sPartialTimer: ReturnType<typeof setTimeout> | null = null
  let s2sPartialStableSince = 0
  let activeS2sTurnId = ''
  let s2sTurnSeq = 0

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
    const phone = d.voiceUsePhonePipeline?.() ?? d.voiceUseS2S?.()
    if (!phone || !d.onS2SPartialStable) return
    if (!d.autoSend.value || getSubmitLock() || micPausedByUser.value) return
    if (partialText.length < endpoint().partialMinChars) return
    if (d.isChatBusy?.() && !isSpeculating.value) return

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
      d.onS2SPartialStable?.(current, turnId)
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

  function cancelSpeculativeState() {
    clearPartialStableTimer()
    if (isSpeculating.value || speculativePartialText) {
      isSpeculating.value = false
      speculativePartialText = null
      d.onSpeculativeCancel()
    }
  }

  function scheduleSpeculativeCheck(partialText: string) {
    clearPartialStableTimer()
    if (!d.canSpeculate(partialText)) return
    if (d.isChatBusy() && !isSpeculating.value) return
    if (partialText.length < endpoint().partialMinChars) return

    partialStableSince = Date.now()
    partialStableTimer = setTimeout(() => {
      partialStableTimer = null
      const current = voiceTranscript.value.trim() || voiceLivePreview.value.trim()
      if (current !== partialText) return
      if (Date.now() - partialStableSince < endpoint().partialStableMs - 50) return
      if (d.autoSend.value && !getSubmitLock() && voiceListening.value && shouldFlushUtterance()) {
        void finishUtterance()
        return
      }
      if (d.isChatBusy() && !isSpeculating.value) return
      if (!d.canSpeculate(current)) return
      if (isSpeculating.value && speculativePartialText === current) return

      partialStable.value = true
      isSpeculating.value = true
      speculativePartialText = current
      d.onSpeculativeStart(current)
    }, endpoint().partialStableMs)
  }

  return {
    isSpeculating,
    partialStable,
    clearPartialStableTimer,
    clearS2sPartialTimer,
    cancelSpeculativeState,
    scheduleS2sPartialStart,
    scheduleSpeculativeCheck,
    getSpeculativePartialText: (): string | null => speculativePartialText,
    setSpeculativePartialText: (v: string | null) => {
      speculativePartialText = v
    },
    getActiveS2sTurn: (): string => activeS2sTurnId,
    clearActiveS2sTurn: () => {
      activeS2sTurnId = ''
    },
  }
}

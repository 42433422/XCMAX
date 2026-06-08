import { computed, ref, type Ref } from 'vue'

export type VoiceChatPhase = 'idle' | 'listening' | 'streaming' | 'speaking'
export type VoiceWorkPhase = 'idle' | 'planning' | 'handoff' | 'orchestrating'

export function createVoiceWorkbenchState() {
  const voiceChatPhase = ref<VoiceChatPhase>('idle')
  const voiceWorkPhase = ref<VoiceWorkPhase>('idle')
  const voiceChatBusy = ref(false)
  const voiceInjectQueue = ref<string[]>([])

  const voiceWorkBusy = computed(() => voiceWorkPhase.value === 'orchestrating')

  function syncWorkPhase(opts: {
    planSession: unknown
    pendingHandoff: unknown
    orchPhase: string
  }) {
    if (opts.orchPhase === 'running' || opts.orchPhase === 'estimating') {
      voiceWorkPhase.value = 'orchestrating'
    } else if (opts.pendingHandoff) {
      voiceWorkPhase.value = 'handoff'
    } else if (opts.planSession) {
      voiceWorkPhase.value = 'planning'
    } else {
      voiceWorkPhase.value = 'idle'
    }
  }

  function pushInject(text: string) {
    const t = text.trim()
    if (t) voiceInjectQueue.value = [...voiceInjectQueue.value, t]
  }

  function clearInjectQueue() {
    voiceInjectQueue.value = []
  }

  return {
    voiceChatPhase,
    voiceWorkPhase,
    voiceChatBusy,
    voiceWorkBusy,
    voiceInjectQueue,
    syncWorkPhase,
    pushInject,
    clearInjectQueue,
  }
}

export type VoiceWorkbenchState = ReturnType<typeof createVoiceWorkbenchState>

/** 是否应阻止重复提交 chat turn（不阻止听麦） */
export function shouldBlockVoiceSubmit(chatBusy: Ref<boolean>, submitLock: boolean): boolean {
  return chatBusy.value || submitLock
}

/** 是否允许连续听麦（执行中也可听） */
export function canKeepVoiceListening(opts: {
  continuous: boolean
  chatBusy: boolean
  submitLock: boolean
  listening: boolean
}): boolean {
  if (!opts.continuous) return false
  if (opts.submitLock) return false
  if (opts.listening) return false
  return true
}

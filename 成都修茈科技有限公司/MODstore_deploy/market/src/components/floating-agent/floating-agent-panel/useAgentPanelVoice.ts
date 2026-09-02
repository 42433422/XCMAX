/**
 * 管家面板语音输入（由 FloatingAgentPanel.vue 原单文件机械迁出，行为不变）。
 */
import { nextTick, watch } from 'vue'
import type { Ref } from 'vue'
import { useAgentStore } from '../../../stores/agent'
import { useVoiceInput } from '../../../composables/agent/useVoiceInput'

interface AgentPanelVoiceCtx {
  draft: Ref<string>
  corpMode: () => boolean
  sendMessage: (text: string, imageDataUrl?: string | null) => Promise<void>
  requestResize: () => void
}

export function useAgentPanelVoice(ctx: AgentPanelVoiceCtx) {
  const agentStore = useAgentStore()

  const {
    state: voiceState,
    error: voiceError,
    isSupported: voiceIsSupported,
    interimText: voiceInterimText,
    loadingHint: voiceLoadingHint,
    sessionReady: voiceSessionReady,
    startListening,
    stopListening: stopVoiceListening,
    speak,
  } = useVoiceInput(async (text: string) => {
    ctx.draft.value = ''
    await ctx.sendMessage(text)
    if (ctx.corpMode()) return
    const msgs = agentStore.messages
    const last = msgs[msgs.length - 1]
    if (last && last.role === 'assistant' && !last.isLoading) {
      await speak(last.content)
    }
  })

  watch(voiceInterimText, (t) => {
    if (voiceState.value === 'listening' && t) {
      ctx.draft.value = t
      nextTick(() => ctx.requestResize())
    }
  })

  function toggleVoice() {
    if (voiceState.value === 'listening') {
      void stopVoiceListening()
    } else {
      voiceError.value = ''
      startListening()
    }
  }

  return {
    voiceState,
    voiceError,
    voiceIsSupported,
    voiceLoadingHint,
    voiceSessionReady,
    toggleVoice,
  }
}

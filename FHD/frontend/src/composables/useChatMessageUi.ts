import { ref, computed, watch, type Ref } from 'vue'
import { sanitizeChatBubbleMarkdown } from '@/utils/sanitizeHtml'
import { speakText, stopSpeaking, cleanTextForSpeech } from '@/utils/tts'
import { estimateMessageHeight, getPerformanceStats } from '@/utils/pretext'
import type { ChatMessage } from './useChatMessages'

export interface UseChatMessageUiDeps {
  messages: Ref<ChatMessage[]>
  chatMessagesRef: Ref<HTMLElement | null>
}

export function useChatMessageUi(deps: UseChatMessageUiDeps) {
  const { messages, chatMessagesRef } = deps

  const expandedMessageIndexes = ref<number[]>([])
  const messageHeights = ref<Map<number, number>>(new Map())
  const chatContainerWidth = ref(600)
  const playingMsgIdx = ref(-1)

  function calculateMessageHeight(content: string, index: number): number {
    const cached = messageHeights.value.get(index)
    if (cached) return cached
    const role = messages.value[index]?.role
    const plainSource =
      role === 'ai'
        ? sanitizeChatBubbleMarkdown(content).replace(/<[^>]*>/g, '')
        : String(content || '').replace(/<[^>]*>/g, '')
    const height = estimateMessageHeight(plainSource, chatContainerWidth.value - 32, 14)
    messageHeights.value.set(index, height)
    return height
  }

  function batchCalculateHeights() {
    if (!chatMessagesRef.value) return
    chatContainerWidth.value = chatMessagesRef.value.clientWidth
    messageHeights.value.clear()
    messages.value.forEach((msg, idx) => {
      calculateMessageHeight(msg.content, idx)
    })
    const stats = getPerformanceStats()
    console.log('📊 Pretext.js 性能统计:', stats)
  }

  function extractSpeakableText(raw: string | undefined | null): string {
    const s = String(raw || '')
    if (!s) return ''
    try {
      const el = document.createElement('div')
      el.innerHTML = sanitizeChatBubbleMarkdown(s)
      return (el.textContent || el.innerText || '').replace(/\s+/g, ' ').trim()
    } catch {
      return s.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
    }
  }

  function canSpeakMessage(msg: { content?: string }): boolean {
    return !!cleanTextForSpeech(extractSpeakableText(msg?.content))
  }

  async function toggleMessageTts(idx: number, rawContent: string | undefined | null) {
    if (playingMsgIdx.value === idx) {
      stopSpeaking()
      playingMsgIdx.value = -1
      return
    }
    if (playingMsgIdx.value !== -1) stopSpeaking()
    const text = cleanTextForSpeech(extractSpeakableText(rawContent))
    if (!text) return
    const myIdx = idx
    playingMsgIdx.value = myIdx
    try {
      void Promise.resolve(speakText(text, {
        onEnd: () => {
          if (playingMsgIdx.value === myIdx) playingMsgIdx.value = -1
        },
        onError: () => {
          if (playingMsgIdx.value === myIdx) playingMsgIdx.value = -1
        },
      })).catch(() => {
        if (playingMsgIdx.value === myIdx) playingMsgIdx.value = -1
      })
    } catch {
      if (playingMsgIdx.value === myIdx) playingMsgIdx.value = -1
    }
  }

  const latestAiMessageIndex = computed(() => {
    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      if (messages.value[i]?.role === 'ai') return i
    }
    return -1
  })

  const isMessageCollapsed = (msg: ChatMessage, idx: number) => {
    if (msg?.role !== 'ai') return false
    if (idx >= latestAiMessageIndex.value) return false
    return !expandedMessageIndexes.value.includes(idx)
  }

  const expandMessage = (idx: number) => {
    if (!expandedMessageIndexes.value.includes(idx)) {
      expandedMessageIndexes.value = [...expandedMessageIndexes.value, idx]
    }
  }

  const collapseMessage = (idx: number) => {
    if (idx >= latestAiMessageIndex.value) return
    if (expandedMessageIndexes.value.includes(idx)) {
      expandedMessageIndexes.value = expandedMessageIndexes.value.filter((x) => x !== idx)
    }
  }

  const getCollapsedPreview = (htmlText: string) => {
    const text = String(htmlText || '')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<[^>]*>/g, '')
      .replace(/\s+/g, ' ')
      .trim()
    if (!text) return '（无内容）'
    return text.length > 120 ? `${text.slice(0, 120)}...` : text
  }

  watch(
    () => messages.value.length,
    () => {
      expandedMessageIndexes.value = expandedMessageIndexes.value.filter(
        (idx) => idx >= 0 && idx < messages.value.length,
      )
    },
  )

  watch(
    () => messages.value.length,
    () => {
      setTimeout(() => batchCalculateHeights(), 50)
    },
  )

  function stopMessageTts() {
    try {
      stopSpeaking()
    } catch {
      /* ignore */
    }
    playingMsgIdx.value = -1
  }

  return {
    messageHeights,
    playingMsgIdx,
    latestAiMessageIndex,
    isMessageCollapsed,
    expandMessage,
    collapseMessage,
    getCollapsedPreview,
    canSpeakMessage,
    toggleMessageTts,
    batchCalculateHeights,
    stopMessageTts,
  }
}

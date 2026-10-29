import { ref, computed, watch, type Ref } from 'vue'
import { plainTextFromChatHtml, plainTextFromChatMarkdown } from '@/utils/sanitizeHtml'
import { speakText, stopSpeaking, cleanTextForSpeech } from '@/utils/tts'
import { estimateMessageHeight } from '@/utils/pretext'
import type { ChatMessage } from './useChatMessages'

export interface UseChatMessageUiDeps {
  messages: Ref<ChatMessage[]>
  chatMessagesRef: Ref<HTMLElement | null>
  sessionKey?: Ref<string>
}

export function useChatMessageUi(deps: UseChatMessageUiDeps) {
  const { messages, chatMessagesRef } = deps

  const expandedMessageIndexes = ref<number[]>([])
  const messageHeights = ref<Map<number, number>>(new Map())
  const playingMsgIdx = ref(-1)
  let speakable = new WeakMap<{ content?: string }, { content: string; text: string }>()

  function batchCalculateHeights() {
    const host = chatMessagesRef.value
    messageHeights.value.clear()
    if (!host) return
    // Only mounted, expanded bodies need a height hint. Their DOM is already sanitized.
    host.querySelectorAll<HTMLElement>('[data-message-index] .message-html').forEach((body) => {
      const index = Number(body.closest<HTMLElement>('[data-message-index]')?.dataset.messageIndex)
      if (Number.isInteger(index)) messageHeights.value.set(index, estimateMessageHeight(body.textContent || '', host.clientWidth - 32, 14))
    })
  }

  function extractSpeakableText(raw: string | undefined | null): string {
    const s = String(raw || '')
    if (!s) return ''
    try {
      return plainTextFromChatMarkdown(s).replace(/\s+/g, ' ').trim()
    } catch {
      return ''
    }
  }

  function canSpeakMessage(msg: { content?: string }): boolean {
    const content = String(msg?.content || '')
    let entry = speakable.get(msg)
    if (!entry || entry.content !== content) {
      entry = { content, text: cleanTextForSpeech(extractSpeakableText(content)) }
      speakable.set(msg, entry)
    }
    return !!entry.text
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
      void Promise.resolve(
        speakText(text, {
          onEnd: () => {
            if (playingMsgIdx.value === myIdx) playingMsgIdx.value = -1
          },
          onError: () => {
            if (playingMsgIdx.value === myIdx) playingMsgIdx.value = -1
          },
        }),
      ).catch(() => {
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
    const text = plainTextFromChatHtml(htmlText).replace(/\s+/g, ' ').trim()
    if (!text) return '（无内容）'
    return text.length > 120 ? `${text.slice(0, 120)}...` : text
  }

  watch(
    () => messages.value.length,
    () => {
      expandedMessageIndexes.value = expandedMessageIndexes.value.filter((idx) => idx >= 0 && idx < messages.value.length)
    },
  )

  watch(() => messages.value.length, batchCalculateHeights, { flush: 'post' })
  watch(() => messages.value[messages.value.length - 1]?.content, () => messageHeights.value.delete(messages.value.length - 1))
  watch([messages, () => deps.sessionKey?.value], () => {
    expandedMessageIndexes.value = []
    messageHeights.value.clear()
    speakable = new WeakMap()
    stopMessageTts()
  }, { flush: 'sync' })

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

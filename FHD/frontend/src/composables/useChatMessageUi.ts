import { ref, computed, watch, type Ref } from 'vue'
import { plainTextFromChatHtml, plainTextFromChatMarkdown } from '@/utils/sanitizeHtml'
import { speakText, cleanTextForSpeech } from '@/utils/tts'
import { estimateMessageHeight } from '@/utils/pretext'
import { clearVoiceQueue, type ChatMessage } from './useChatMessages'

export interface UseChatMessageUiDeps {
  messages: Ref<ChatMessage[]>
  chatMessagesRef: Ref<HTMLElement | null>
  sessionKey?: Ref<string>
}

export function useChatMessageUi(deps: UseChatMessageUiDeps) {
  const { messages, chatMessagesRef } = deps

  /** 已展开消息的身份键（不是下标，避免历史分页后错位）。 */
  const expandedMessageKeys = ref<string[]>([])
  const messageHeights = ref<Map<number, number>>(new Map())
  const playingMsgIdx = ref(-1)
  let speechGeneration = 0
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
    const wasPlaying = playingMsgIdx.value === idx
    stopMessageTts()
    if (wasPlaying) return
    const text = cleanTextForSpeech(extractSpeakableText(rawContent))
    if (!text) return
    const generation = speechGeneration
    playingMsgIdx.value = idx
    const finish = () => {
      if (speechGeneration === generation) playingMsgIdx.value = -1
    }
    void speakText(text, { onEnd: finish }).then(finish, finish)
  }

  const latestAiMessageIndex = computed(() => {
    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      if (messages.value[i]?.role === 'ai') return i
    }
    return -1
  })

  /**
   * 折叠状态按消息身份保存，而不是数组下标。
   * 历史窗口分页、消息插入都会让下标漂移，旧实现会把折叠态错挂到别的消息上。
   */
  function messageCollapseKey(msg: ChatMessage): string {
    const id = String(msg?.persistence?.id || msg?.turnId || '').trim()
    if (id) return id
    return `${String(msg?.time || '')}|${String(msg?.content || '').slice(0, 40)}`
  }

  /**
   * 普通对话不折叠；只有正文特别长时才折叠。
   * 折叠的唯一目的从「历史消息统一压成摘要」改成「超长内容不刷屏」，
   * 工具链的折叠由 AgentStepChain / AgentRunTrace 自己负责。
   */
  const LONG_MESSAGE_COLLAPSE_CHARS = 1200

  /** 长度判定要净化整段正文，按消息+内容缓存，避免每帧重算。 */
  const foldableCache = new WeakMap<{ content?: string }, { content: string; value: boolean }>()

  /** 该消息是否允许折叠（超长正文才允许）。 */
  const canCollapseMessage = (msg: ChatMessage) => {
    if (msg?.role !== 'ai') return false
    if (msg.streamingShell) return false
    const content = String(msg?.content || '')
    let entry = foldableCache.get(msg)
    if (!entry || entry.content !== content) {
      const length = plainTextFromChatHtml(content).replace(/\s+/g, '').length
      entry = { content, value: length > LONG_MESSAGE_COLLAPSE_CHARS }
      foldableCache.set(msg, entry)
    }
    return entry.value
  }

  const isMessageCollapsed = (msg: ChatMessage, idx: number) => {
    if (!canCollapseMessage(msg)) return false
    if (idx >= latestAiMessageIndex.value) return false
    return !expandedMessageKeys.value.includes(messageCollapseKey(msg))
  }

  const expandMessage = (idx: number) => {
    const msg = messages.value[idx]
    if (!msg) return
    const key = messageCollapseKey(msg)
    if (!expandedMessageKeys.value.includes(key)) {
      expandedMessageKeys.value = [...expandedMessageKeys.value, key]
    }
  }

  const collapseMessage = (idx: number) => {
    if (idx >= latestAiMessageIndex.value) return
    const msg = messages.value[idx]
    if (!msg) return
    const key = messageCollapseKey(msg)
    if (expandedMessageKeys.value.includes(key)) {
      expandedMessageKeys.value = expandedMessageKeys.value.filter((x) => x !== key)
    }
  }

  watch(() => messages.value.length, batchCalculateHeights, { flush: 'post' })
  watch(() => messages.value[messages.value.length - 1]?.content, () => messageHeights.value.delete(messages.value.length - 1))
  watch(messages, () => {
    speakable = new WeakMap()
    stopMessageTts()
  }, { flush: 'sync' })
  watch(() => deps.sessionKey?.value, () => {
    expandedMessageKeys.value = []
    messageHeights.value.clear()
    speakable = new WeakMap()
    stopMessageTts()
  }, { flush: 'sync' })

  function stopMessageTts() {
    speechGeneration++
    clearVoiceQueue()
    playingMsgIdx.value = -1
  }

  return {
    messageHeights,
    playingMsgIdx,
    latestAiMessageIndex,
    isMessageCollapsed,
    canCollapseMessage,
    expandMessage,
    collapseMessage,
    canSpeakMessage,
    toggleMessageTts,
    batchCalculateHeights,
    stopMessageTts,
  }
}

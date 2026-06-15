import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, nextTick } from 'vue'

vi.mock('@/utils/sanitizeHtml', () => ({
  sanitizeChatBubbleMarkdown: vi.fn((s: string) => s),
}))

vi.mock('@/utils/chatBubbleDisplay', () => ({
  plainTextFromMessageContent: vi.fn((s: string) => s?.replace(/<[^>]*>/g, '') || ''),
  stripToolInvocationLeaks: vi.fn((s: string) => s),
}))

vi.mock('@/utils/tts', () => ({
  speakText: vi.fn().mockResolvedValue(undefined),
  stopSpeaking: vi.fn(),
  cleanTextForSpeech: vi.fn((s: string) => s?.trim() || ''),
  prepareTextForSpeech: vi.fn((s: string) => s || ''),
}))

vi.mock('@/composables/useTutorialSpeech', () => ({
  getTutorialSpeech: vi.fn(() => ({ stop: vi.fn() })),
}))

vi.mock('@/utils/pretext', () => ({
  estimateMessageHeight: vi.fn(() => 100),
}))

import { useChatMessageUi } from './useChatMessageUi'
import { speakText, stopSpeaking, cleanTextForSpeech } from '@/utils/tts'

describe('useChatMessageUi', () => {
  let messages: ReturnType<typeof ref<Array<{ content: string; role: string }>>>
  let chatMessagesRef: ReturnType<typeof ref<HTMLElement | null>>

  beforeEach(() => {
    vi.clearAllMocks()
    messages = ref([
      { content: 'Hello', role: 'user' },
      { content: 'Hi there!', role: 'ai' },
      { content: 'How are you?', role: 'user' },
      { content: 'I am fine', role: 'ai' },
    ])
    chatMessagesRef = ref(null)
  })

  it('returns composable API', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    expect(ui.messageHeights).toBeDefined()
    expect(ui.playingMsgIdx).toBeDefined()
    expect(ui.latestAiMessageIndex).toBeDefined()
    expect(typeof ui.isMessageCollapsed).toBe('function')
    expect(typeof ui.expandMessage).toBe('function')
    expect(typeof ui.collapseMessage).toBe('function')
    expect(typeof ui.getCollapsedPreview).toBe('function')
    expect(typeof ui.canSpeakMessage).toBe('function')
    expect(typeof ui.toggleMessageTts).toBe('function')
    expect(typeof ui.batchCalculateHeights).toBe('function')
    expect(typeof ui.stopMessageTts).toBe('function')
  })

  it('latestAiMessageIndex returns last AI message index', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    expect(ui.latestAiMessageIndex.value).toBe(3)
  })

  it('latestAiMessageIndex returns -1 when no AI messages', () => {
    messages.value = [
      { content: 'Hello', role: 'user' },
      { content: 'How are you?', role: 'user' },
    ]
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    expect(ui.latestAiMessageIndex.value).toBe(-1)
  })

  it('isMessageCollapsed returns false for non-AI messages', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    expect(ui.isMessageCollapsed(messages.value[0], 0)).toBe(false)
  })

  it('isMessageCollapsed returns false for latest AI message', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    expect(ui.isMessageCollapsed(messages.value[3], 3)).toBe(false)
  })

  it('isMessageCollapsed returns true for older AI messages not expanded', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    expect(ui.isMessageCollapsed(messages.value[1], 1)).toBe(true)
  })

  it('expandMessage adds index to expanded list', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    ui.expandMessage(1)
    expect(ui.isMessageCollapsed(messages.value[1], 1)).toBe(false)
  })

  it('expandMessage does not add duplicate index', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    ui.expandMessage(1)
    ui.expandMessage(1)
    // Verify no duplicate: still not collapsed means it's expanded, and calling collapse once should work
    expect(ui.isMessageCollapsed(messages.value[1], 1)).toBe(false)
    ui.collapseMessage(1)
    expect(ui.isMessageCollapsed(messages.value[1], 1)).toBe(true)
  })

  it('collapseMessage removes index from expanded list', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    ui.expandMessage(1)
    ui.collapseMessage(1)
    expect(ui.isMessageCollapsed(messages.value[1], 1)).toBe(true)
  })

  it('collapseMessage does not collapse latest AI message', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    ui.collapseMessage(3)
    expect(ui.isMessageCollapsed(messages.value[3], 3)).toBe(false)
  })

  it('canSpeakMessage returns true for speakable content', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    expect(ui.canSpeakMessage({ content: 'Hello world' })).toBe(true)
  })

  it('canSpeakMessage returns false for empty content', () => {
    vi.mocked(cleanTextForSpeech).mockReturnValueOnce('')
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    expect(ui.canSpeakMessage({ content: '' })).toBe(false)
  })

  it('toggleMessageTts starts speaking when not playing', async () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    await ui.toggleMessageTts(1, 'Hello')
    expect(speakText).toHaveBeenCalled()
    expect(ui.playingMsgIdx.value).toBe(1)
  })

  it('toggleMessageTts stops speaking when same message is playing', async () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    await ui.toggleMessageTts(1, 'Hello')
    await ui.toggleMessageTts(1, 'Hello')
    expect(stopSpeaking).toHaveBeenCalled()
    expect(ui.playingMsgIdx.value).toBe(-1)
  })

  it('stopMessageTts stops speaking and resets index', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    ui.playingMsgIdx.value = 2
    ui.stopMessageTts()
    expect(stopSpeaking).toHaveBeenCalled()
    expect(ui.playingMsgIdx.value).toBe(-1)
  })

  it('batchCalculateHeights does nothing when chatMessagesRef is null', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    ui.batchCalculateHeights()
    // Should not throw
  })

  it('getCollapsedPreview returns text preview', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    const preview = ui.getCollapsedPreview('Hello world')
    expect(typeof preview).toBe('string')
    expect(preview.length).toBeGreaterThan(0)
  })

  it('getCollapsedPreview returns placeholder for empty content', () => {
    vi.mocked(cleanTextForSpeech).mockReturnValueOnce('')
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    const preview = ui.getCollapsedPreview('')
    expect(preview).toBe('（无内容）')
  })

  it('playingMsgIdx initializes to -1', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    expect(ui.playingMsgIdx.value).toBe(-1)
  })
})

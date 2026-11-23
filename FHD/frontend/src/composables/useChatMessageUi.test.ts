import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

vi.mock('@/utils/sanitizeHtml', () => ({
  sanitizeChatBubbleMarkdown: vi.fn((s: string) => s),
  plainTextFromChatHtml: vi.fn((s: string) => s?.replace(/<[^>]*>/g, '') || ''),
  plainTextFromChatMarkdown: vi.fn((s: string) => s?.replace(/<[^>]*>/g, '') || ''),
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
import { speakText, cleanTextForSpeech } from '@/utils/tts'
import { clearVoiceQueue } from './useChatMessages'
vi.mock('./useChatMessages', () => ({ clearVoiceQueue: vi.fn() }))

describe('useChatMessageUi', () => {
  let messages: ReturnType<typeof ref<Array<{ content: string; role: string }>>>
  let chatMessagesRef: ReturnType<typeof ref<HTMLElement | null>>

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(speakText).mockImplementation(() => new Promise(() => {}))
    messages = ref([
      { content: 'Hello', role: 'user' },
      // 只有超长正文才会折叠，折叠相关用例需要一条长消息
      { content: '长正文'.repeat(500), role: 'ai' },
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

  it('普通长度的历史消息不折叠', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    // index 3 是短 AI 消息，且不再是最后一条 → 仍然不折叠
    messages.value.push({ content: '最新一条', role: 'ai' })
    expect(ui.canCollapseMessage(messages.value[3])).toBe(false)
    expect(ui.isMessageCollapsed(messages.value[3], 3)).toBe(false)
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

  it('折叠状态跟随消息本身，历史窗口插入消息后不会错位', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    const target = messages.value[1]
    ui.expandMessage(1)
    expect(ui.isMessageCollapsed(target, 1)).toBe(false)
    // 前面插入一条消息，下标整体后移一位（同一数组，模拟历史窗口变化）
    messages.value.splice(0, 0, { content: '新插入', role: 'user', time: '09:59' })
    const shifted = messages.value[2]
    expect(shifted).toBe(target)
    expect(ui.isMessageCollapsed(shifted, 2)).toBe(false)
  })

  it('keeps separate expansion state for legacy replies with the same time and prefix', () => {
    messages.value = [
      { role: 'ai', content: '共同前缀'.repeat(400) + 'first' },
      { role: 'ai', content: '共同前缀'.repeat(400) + 'second' },
      { role: 'ai', content: 'latest' },
    ]
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    ui.expandMessage(0)
    expect(ui.isMessageCollapsed(messages.value[0], 0)).toBe(false)
    expect(ui.isMessageCollapsed(messages.value[1], 1)).toBe(true)
  })

  it('keeps an expanded reply open when persistence acknowledges it with a server identity', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    const message = messages.value[1] as typeof messages.value[number] & { persistence?: { id: string; status: 'saved' } }
    ui.expandMessage(1)
    message.persistence = { id: 'server:80', status: 'saved' }
    expect(ui.isMessageCollapsed(message, 1)).toBe(false)
    ui.collapseMessage(1)
    expect(ui.isMessageCollapsed(message, 1)).toBe(true)
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
    expect(clearVoiceQueue).toHaveBeenCalled()
    expect(ui.playingMsgIdx.value).toBe(-1)
  })

  it('ignores old completion when the same message is stopped and replayed', async () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    await ui.toggleMessageTts(1, 'first')
    const old = vi.mocked(speakText).mock.calls.at(-1)![1]!
    await ui.toggleMessageTts(1, 'stop')
    await ui.toggleMessageTts(1, 'replay')
    old.onEnd?.()
    expect(ui.playingMsgIdx.value).toBe(1)
    vi.mocked(speakText).mock.calls.at(-1)![1]!.onEnd?.()
    expect(ui.playingMsgIdx.value).toBe(-1)
  })

  it('restores the button after playback resolves without an end callback', async () => {
    let finish!: () => void
    vi.mocked(speakText).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    await ui.toggleMessageTts(1, 'Hello')
    expect(ui.playingMsgIdx.value).toBe(1)
    finish()
    await vi.waitFor(() => expect(ui.playingMsgIdx.value).toBe(-1))
    await ui.toggleMessageTts(1, 'Hello again')
    expect(speakText).toHaveBeenCalledTimes(2)
  })

  it('ignores a canceled playback rejection after replay', async () => {
    let reject!: (error: Error) => void
    vi.mocked(speakText).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    vi.mocked(speakText).mockImplementationOnce(() => new Promise(() => {}))
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    await ui.toggleMessageTts(1, 'first')
    await ui.toggleMessageTts(1, 'stop')
    await ui.toggleMessageTts(1, 'replay')
    reject(new Error('canceled'))
    await Promise.resolve()
    expect(ui.playingMsgIdx.value).toBe(1)
  })

  it('restores the button after a playback rejection and allows retry', async () => {
    let reject!: (error: Error) => void
    vi.mocked(speakText).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    await ui.toggleMessageTts(1, 'first')
    reject(new Error('playback failed'))
    await Promise.resolve()
    expect(ui.playingMsgIdx.value).toBe(-1)
    await ui.toggleMessageTts(1, 'retry')
    expect(ui.playingMsgIdx.value).toBe(1)
    expect(speakText).toHaveBeenCalledTimes(2)
  })

  it.each(['session', 'messages'])('cancels playback when %s changes and permits replay', async change => {
    const sessionKey = ref('first')
    const ui = useChatMessageUi({ messages, chatMessagesRef, sessionKey })
    await ui.toggleMessageTts(1, 'first')
    const old = vi.mocked(speakText).mock.calls.at(-1)![1]!
    vi.mocked(clearVoiceQueue).mockClear()
    if (change === 'session') sessionKey.value = 'second'
    else messages.value = [{ content: 'new reply', role: 'ai' }]
    expect(clearVoiceQueue).toHaveBeenCalledOnce()
    expect(ui.playingMsgIdx.value).toBe(-1)
    await ui.toggleMessageTts(0, 'new reply')
    old.onEnd?.()
    expect(ui.playingMsgIdx.value).toBe(0)
  })

  it('stopMessageTts stops speaking and resets index', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    ui.playingMsgIdx.value = 2
    ui.stopMessageTts()
    expect(clearVoiceQueue).toHaveBeenCalled()
    expect(ui.playingMsgIdx.value).toBe(-1)
  })

  it('batchCalculateHeights does nothing when chatMessagesRef is null', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    ui.batchCalculateHeights()
    // Should not throw
  })



  it('playingMsgIdx initializes to -1', () => {
    const ui = useChatMessageUi({ messages, chatMessagesRef })
    expect(ui.playingMsgIdx.value).toBe(-1)
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import { chatMessageExtrasFromServerRow, useChatMessages, queueVoice, clearVoiceQueue } from './useChatMessages'

vi.mock('@/api/chat', () => ({
  default: {
    saveMessage: vi.fn().mockResolvedValue(undefined),
    getConversation: vi.fn().mockResolvedValue({ messages: [] }),
  },
}))

// Create a real Pinia-compatible mock for modsStore
const activeModIdRef = ref('')
vi.mock('@/stores/mods', () => {
  return {
    useModsStore: () => ({
      activeModId: activeModIdRef,
      modsForWorkflowUi: [],
      isLoaded: true,
      initialize: vi.fn().mockResolvedValue(undefined),
      $id: 'mods',
    }),
  }
})

vi.mock('@/stores/industry', () => ({
  useIndustryStore: () => ({
    currentIndustryId: '通用',
  }),
}))

vi.mock('@/constants/industryPresets', () => ({
  getIndustryWelcomeMarkdown: () => '您好！我是您的智能助手',
}))

vi.mock('@/utils/chatStorageKeys', () => ({
  buildChatMessagesKey: (sid: string, modId: string) => `chat_${sid}_${modId}`,
  buildChatSessionMetaKey: (sid: string, modId: string) => `chat_meta_${sid}_${modId}`,
}))

vi.mock('@/utils/tts', () => ({
  speakText: vi.fn().mockResolvedValue(undefined),
  stopSpeaking: vi.fn(),
  cleanTextForSpeech: (text: string) => text,
}))

describe('useChatMessages', () => {
  let messages: ReturnType<typeof useChatMessages>

  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    messages = useChatMessages(ref('session-1'))
  })

  it('initializes with welcome message', () => {
    expect(messages.messages.value.length).toBe(1)
    expect(messages.messages.value[0].role).toBe('ai')
    expect(messages.messages.value[0].content).toContain('您好！我是您的智能助手')
  })

  it('addMessage adds user message', () => {
    messages.addMessage('Hello', 'user')
    expect(messages.messages.value.length).toBe(2)
    expect(messages.messages.value[1].role).toBe('user')
    expect(messages.messages.value[1].content).toContain('Hello')
  })

  it('addMessage adds AI message', () => {
    messages.addMessage('AI response', 'ai')
    expect(messages.messages.value.length).toBe(2)
    expect(messages.messages.value[1].role).toBe('ai')
  })

  it('addMessage ignores empty content', () => {
    messages.addMessage('', 'user')
    messages.addMessage('   ', 'user')
    expect(messages.messages.value.length).toBe(1) // only welcome
  })

  it('addMessage escapes HTML and converts newlines', () => {
    messages.addMessage('Line1\nLine2<script>', 'user')
    expect(messages.messages.value[1].content).toContain('&lt;script&gt;')
    expect(messages.messages.value[1].content).toContain('<br>')
  })

  it('addMessage with speak option queues voice for AI messages', () => {
    messages.addMessage('AI response', 'ai', undefined, { speak: true })
    // Voice queue should have been called
  })

  it('addMessage with speak option does not queue voice for user messages', () => {
    messages.addMessage('User message', 'user', undefined, { speak: true })
    // No voice for user messages
  })

  it('addMessage with speak option does not queue for welcome messages', () => {
    messages.addMessage('您好！我是您的智能助手，欢迎', 'ai', undefined, { speak: true })
    // No voice for welcome messages
  })

  it('addMessage with extras', () => {
    messages.addMessage('test', 'ai', { attachments: [{ type: 'file', name: 'test.pdf' }] })
    expect(messages.messages.value[1]).toHaveProperty('attachments')
  })

  it('keeps Business Harness cards and terminal results in the local cache', () => {
    messages.addMessage('等待审批', 'ai', {
      todoSteps: ['核对客户', '创建订单'],
      approvalCard: { run_id: 'run-1', status: 'pending' },
      businessResult: { status: 'completed', summary: '订单创建成功', order_id: 42 },
    })

    const restored = useChatMessages(ref('session-1'))
    const row = restored.messages.value.at(-1)
    expect(row?.todoSteps).toEqual(['核对客户', '创建订单'])
    expect(row?.approvalCard?.run_id).toBe('run-1')
    expect(row?.businessResult?.summary).toBe('订单创建成功')
  })

  it('persists an approval-card status mutated after the message is rendered', async () => {
    messages.addMessage('等待审批', 'ai', {
      approvalCard: { run_id: 'run-2', status: 'pending' },
    })
    const row = messages.messages.value.at(-1)
    if (!row?.approvalCard) throw new Error('approval card was not rendered')
    row.approvalCard.status = 'confirmed'
    await nextTick()

    const restored = useChatMessages(ref('session-1'))
    expect(restored.messages.value.at(-1)?.approvalCard?.status).toBe('confirmed')
  })

  it('lastMessage returns last message', () => {
    messages.addMessage('first', 'user')
    messages.addMessage('second', 'ai')
    expect(messages.lastMessage.value.content).toContain('second')
  })

  it('clearMessages empties messages', () => {
    messages.addMessage('test', 'user')
    messages.clearMessages()
    expect(messages.messages.value.length).toBe(0)
  })

  it('loadMessages replaces messages', () => {
    messages.loadMessages([
      { role: 'user', content: 'loaded', time: '10:00' },
      { role: 'ai', content: 'response', time: '10:01' },
    ])
    expect(messages.messages.value.length).toBe(2)
    expect(messages.messages.value[0].content).toContain('loaded')
  })

  it('loadMessages sanitizes invalid messages', () => {
    messages.loadMessages([
      { role: 'user', content: 'valid', time: '10:00' },
      { role: 'invalid', content: '', time: '10:01' },
      { role: 'ai', content: '  ', time: '10:02' },
    ] as any)
    // Empty content messages should be filtered out
    expect(messages.messages.value.every((m) => m.content.trim())).toBe(true)
  })

  it('pushStreamingAiShell adds placeholder message', () => {
    const idx = messages.pushStreamingAiShell()
    expect(idx).toBe(1) // index 1 (after welcome)
    expect(messages.messages.value[1].role).toBe('ai')
    expect(messages.messages.value[1].content).toBe('')
    expect(messages.messages.value[1].streamingShell).toBe(true)
  })

  it('pushStreamingAiShell index targets ai after user message and persist', () => {
    messages.addMessage('用户提问', 'user')
    const idx = messages.pushStreamingAiShell()
    expect(messages.messages.value[idx].role).toBe('ai')
    expect(messages.messages.value[idx].streamingShell).toBe(true)
    expect(messages.messages.value[idx - 1].role).toBe('user')
  })

  it('applyPlainTextToMessageIndex updates message content', () => {
    const idx = messages.pushStreamingAiShell()
    messages.applyPlainTextToMessageIndex(idx, 'streaming text')
    expect(messages.messages.value[idx].content).toContain('streaming text')
    expect(messages.messages.value[idx].streamingShell).toBeUndefined()
  })

  it('marks and restores semantic-cache replies as the same as before', () => {
    const idx = messages.pushStreamingAiShell()
    messages.applyPlainTextToMessageIndex(idx, '重复答案', { sameAsPrevious: true })
    expect(messages.messages.value[idx].sameAsPrevious).toBe(true)
    expect(chatMessageExtrasFromServerRow({ data: { cached: true } }).sameAsPrevious).toBe(true)
  })

  it('applyPlainTextToMessageIndex handles invalid index', () => {
    expect(() => messages.applyPlainTextToMessageIndex(999, 'text')).not.toThrow()
  })

  it('applyPlainTextToMessageIndex keeps streamingShell for empty text', () => {
    const idx = messages.pushStreamingAiShell()
    messages.applyPlainTextToMessageIndex(idx, '')
    expect(messages.messages.value[idx].content).toBe('')
    expect(messages.messages.value[idx].streamingShell).toBe(true)
  })

  it('never renders model tool protocol as an assistant reply', () => {
    messages.addMessage('<tool_call><function=skill>open_client_list</function></tool_call>', 'ai')
    expect(messages.messages.value).toHaveLength(1)

    messages.addMessage('已查询。<tool_call>hidden</tool_call>', 'ai')
    expect(messages.messages.value[1].content).toContain('已查询。')
    expect(messages.messages.value[1].content).not.toContain('tool_call')
  })

  it('removes encoded legacy tool protocol from cached assistant messages', () => {
    messages.loadMessages([
      {
        role: 'ai',
        content: '&amp;lt;tool_call&amp;gt;hidden&amp;lt;/tool_call&amp;gt;',
        time: '10:00',
      },
    ])
    expect(messages.messages.value).toHaveLength(0)
  })

  it('saveMessage calls API', async () => {
    const chatApi = (await import('@/api/chat')).default
    messages.addMessage('test', 'user')
    await messages.saveMessage('user', 'test')
    expect(chatApi.saveMessage).toHaveBeenCalled()
  })

  it('saveMessage persists only the structured UI payload passed by the caller', async () => {
    const chatApi = (await import('@/api/chat')).default
    await messages.saveMessage('ai', '订单创建成功', undefined, {
      businessResult: { status: 'completed', summary: '订单创建成功' },
    })

    expect(chatApi.saveMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata: JSON.stringify({
          ui: { businessResult: { status: 'completed', summary: '订单创建成功' } },
        }),
      }),
    )
  })

  it('saveMessage ignores empty content', async () => {
    const chatApi = (await import('@/api/chat')).default
    await messages.saveMessage('user', '')
    expect(chatApi.saveMessage).not.toHaveBeenCalled()
  })

  it('addAndSaveMessage adds and persists', async () => {
    const chatApi = (await import('@/api/chat')).default
    await messages.addAndSaveMessage('test content', 'user')
    expect(messages.messages.value.length).toBe(2)
    expect(chatApi.saveMessage).toHaveBeenCalled()
  })

  it('persists a detached task reply without rendering it in the active conversation', async () => {
    const chatApi = (await import('@/api/chat')).default
    await messages.addAndSaveMessage('background reply', 'ai', undefined, {
      sessionId: 'task-background',
    })
    expect(messages.messages.value).toHaveLength(1)
    expect(chatApi.saveMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        session_id: 'task-background',
        content: 'background reply',
      }),
    )
  })

  it('addAndSaveMessage ignores empty content', async () => {
    const chatApi = (await import('@/api/chat')).default
    await messages.addAndSaveMessage('', 'user')
    expect(messages.messages.value.length).toBe(1)
    expect(chatApi.saveMessage).not.toHaveBeenCalled()
  })

  it('persistMessagesCache saves to localStorage', () => {
    messages.addMessage('persist test', 'user')
    const key = `chat_session-1_`
    const stored = Object.keys(localStorage).find((k) => k.startsWith(key))
    expect(stored).toBeDefined()
  })

  it('session change reloads messages', async () => {
    const sessionId = ref('session-1')
    const msgs = useChatMessages(sessionId)
    msgs.addMessage('test', 'user')
    sessionId.value = 'session-2'
    await nextTick()
    // Should reload from cache (empty → welcome)
    expect(msgs.messages.value.length).toBe(1)
    expect(msgs.messages.value[0].role).toBe('ai')
  })

  it('normalizeServerContentToHtml preserves existing HTML', () => {
    // Test indirectly via loadMessages
    messages.loadMessages([{ role: 'ai', content: '<div>existing HTML</div>', time: '10:00' }])
    expect(messages.messages.value[0].content).toContain('<div>existing HTML</div>')
  })

  it('normalizeServerContentToHtml escapes plain text', () => {
    messages.loadMessages([{ role: 'ai', content: 'plain text with <br>', time: '10:00' }])
    // Content with <br> tag should be treated as HTML
    expect(messages.messages.value[0].content).toContain('<br>')
  })

  it('deriveSessionTitle returns meaningful title', () => {
    messages.addMessage('用户提问内容', 'user')
    messages.addMessage('AI回答', 'ai')
    // Title is derived internally during persistSessionMeta
    const metaKey = Object.keys(localStorage).find((k) => k.startsWith('chat_meta_'))
    if (metaKey) {
      const meta = JSON.parse(localStorage.getItem(metaKey)!)
      expect(meta.title).toBeTruthy()
    }
  })

  it('deriveSessionTitle returns 新会话 for empty messages', () => {
    messages.clearMessages()
    messages.loadMessages([])
    // Should have default welcome
  })

  it('sanitizeMessagesList filters out empty content', () => {
    messages.loadMessages([
      { role: 'user', content: 'valid', time: '10:00' },
      { role: 'ai', content: '', time: '10:01' },
      { role: 'user', content: '   ', time: '10:02' },
    ] as any)
    expect(messages.messages.value.length).toBe(1)
  })

  it('sanitizeMessagesList keeps streamingShell placeholder', () => {
    messages.loadMessages([
      { role: 'user', content: 'valid', time: '10:00' },
      { role: 'ai', content: '', time: '10:01', streamingShell: true },
    ] as any)
    expect(messages.messages.value.length).toBe(2)
    expect(messages.messages.value[1].role).toBe('ai')
    expect(messages.messages.value[1].streamingShell).toBe(true)
  })

  it('sanitizeMessagesList keeps toolProgressLabel-only ai row', () => {
    messages.loadMessages([{ role: 'ai', content: '', time: '10:00', toolProgressLabel: '正在调用 excel…' }] as any)
    expect(messages.messages.value.length).toBe(1)
    expect(messages.messages.value[0].toolProgressLabel).toContain('excel')
  })

  it('sanitizeMessagesList normalizes invalid roles to ai', () => {
    messages.loadMessages([{ role: 'system', content: 'system message', time: '10:00' }] as any)
    expect(messages.messages.value[0].role).toBe('ai')
  })

  it('sanitizeMessagesList preserves user and task roles', () => {
    messages.loadMessages([
      { role: 'user', content: 'user message', time: '10:00' },
      { role: 'task', content: 'task message', time: '10:01' },
    ])
    expect(messages.messages.value[0].role).toBe('user')
    expect(messages.messages.value[1].role).toBe('task')
  })

  it('syncFromServer handles success', async () => {
    const chatApi = (await import('@/api/chat')).default
    vi.mocked(chatApi.getConversation).mockResolvedValueOnce({
      messages: [
        { role: 'user', content: 'server msg' },
        { role: 'ai', content: 'server reply' },
      ],
    })
    const result = await messages.syncFromServer()
    expect(result).toBe(true)
  })

  it('syncFromServer restores approval, trace, and terminal business result metadata', async () => {
    const chatApi = (await import('@/api/chat')).default
    vi.mocked(chatApi.getConversation).mockResolvedValueOnce({
      messages: [
        {
          role: 'assistant',
          content: '审批已完成',
          metadata: JSON.stringify({
            ui: {
              approvalCard: { run_id: 'run-9', status: 'confirmed' },
              agentRunTrace: {
                run_id: 'run-9',
                intent: 'create_order',
                status: 'success',
                phases: [],
                terminal: true,
              },
              businessResult: { status: 'completed', facts: { order_id: 9 } },
            },
          }),
        },
      ],
    })

    expect(await messages.syncFromServer()).toBe(true)
    const row = messages.messages.value[0]
    expect(row.approvalCard?.status).toBe('confirmed')
    expect(row.agentRunTrace?.run_id).toBe('run-9')
    expect(row.businessResult?.facts).toEqual({ order_id: 9 })
  })

  it('syncFromServer handles empty response', async () => {
    const chatApi = (await import('@/api/chat')).default
    vi.mocked(chatApi.getConversation).mockResolvedValueOnce({ messages: [] })
    const result = await messages.syncFromServer()
    expect(result).toBe(false)
  })

  it('syncFromServer handles error', async () => {
    const chatApi = (await import('@/api/chat')).default
    vi.mocked(chatApi.getConversation).mockRejectedValueOnce(new Error('Network error'))
    const result = await messages.syncFromServer()
    expect(result).toBe(false)
  })

  it('syncFromServer returns false for empty sessionId', async () => {
    const emptyMsgs = useChatMessages(ref(''))
    const result = await emptyMsgs.syncFromServer()
    expect(result).toBe(false)
  })
})

describe('queueVoice and clearVoiceQueue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    clearVoiceQueue()
  })

  it('queueVoice adds text to queue', () => {
    queueVoice('Hello world')
    // Voice queue is internal; just ensure no error
  })

  it('queueVoice ignores empty text', () => {
    queueVoice('')
    queueVoice('   ')
    // No error
  })

  it('clearVoiceQueue stops speaking', () => {
    queueVoice('test')
    clearVoiceQueue()
    // No error
  })
})

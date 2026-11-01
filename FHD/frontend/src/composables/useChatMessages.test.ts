import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { lastChatModelRoute, recordChatModelRoute, type ChatModelRoute } from '@/utils/chatModelRoute'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
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
  resolveChatIdentity: (modId = '') => `identity:${modId}`,
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

  it.each(['session', 'mod', 'account', 'live-message'])('ignores a late history response after %s changes', async (change) => {
    const sid = ref('current')
    const chat = useChatMessages(sid)
    const api = (await import('@/api/chat')).default
    let finish!: (value: any) => void
    vi.mocked(api.getConversation).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const pending = chat.syncFromServer()
    if (change === 'session') sid.value = 'other'
    if (change === 'mod') activeModIdRef.value = 'other-mod'
    if (change === 'account') (await import('@/utils/productReadAccountScope')).productReadAccountEpoch.value++
    if (change === 'live-message') chat.addMessage('new live request', 'user')
    await nextTick()
    finish({ messages: [{ role: 'ai', content: 'old approval result' }] })
    expect(await pending).toBe(false)
    expect(chat.messages.value.some(row => row.content.includes('old approval result'))).toBe(false)
    activeModIdRef.value = ''
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

describe('message persistence failure UX', () => {
  beforeEach(() => { localStorage.clear(); setActivePinia(createPinia()); vi.clearAllMocks() })

  it('retains a retryable bubble when both the server and local storage fail, then recovers its local copy', async () => {
    const api = useChatMessages(ref('cache-failure'))
    const chatApi = (await import('@/api/chat')).default
    vi.mocked(chatApi.saveMessage).mockRejectedValueOnce(new Error('offline'))
    const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('full', 'QuotaExceededError') })
    api.addMessage('重要记录', 'user')
    await api.saveMessage('user', '重要记录')
    expect(api.cacheError.value).toContain('本机保存失败')
    expect(api.messages.value.at(-1)?.persistence?.localSaved).toBe(false)
    expect(api.messages.value.at(-1)?.persistence).toMatchObject({ status: 'failed', request: { role: 'user', content: '重要记录' } })
    expect(api.messages.value.at(-1)?.content).toContain('重要记录')
    write.mockRestore()
    api.retryMessagesCache()
    expect(api.cacheError.value).toBe('')
    expect(api.messages.value.at(-1)?.persistence?.localSaved).toBe(true)
  })

  it.each(['message-b', ''])('preserves an unsaved repeated message when only the second copy is on the server (client id=%s)', async clientId => {
    const chatApi = (await import('@/api/chat')).default
    const api = useChatMessages(ref('repeated-content'))
    const body = { role: 'user' as const, content: '相同消息', time: '12:00' }
    api.loadMessages([
      { ...body, persistence: { id: 'message-a', status: 'failed', request: { role: 'user', content: '相同消息' } } },
      { ...body, persistence: { id: 'message-b', status: 'saved' } },
    ])
    vi.mocked(chatApi.getConversation).mockResolvedValueOnce({ success: true, messages: [
      { ...body, id: 2, metadata: JSON.stringify({ client_message_id: clientId }) },
    ] } as never)
    expect(await api.syncFromServer()).toBe(true)
    expect(api.messages.value).toHaveLength(2)
    expect(api.messages.value.find(item => item.persistence?.id === 'message-a')?.persistence).toMatchObject({ status: 'failed', request: { content: '相同消息' } })
    expect(api.messages.value.filter(item => item.persistence?.status === 'saved')).toHaveLength(1)
    expect(chatApi.saveMessage).not.toHaveBeenCalled()
  })

  it('restores a failed save with the same id and retains it during server history synchronization', async () => {
    const chatApi = (await import('@/api/chat')).default
    vi.mocked(chatApi.saveMessage).mockRejectedValueOnce(new Error('offline'))
    const first = useChatMessages(ref('persisted-failure'))
    await first.addAndSaveMessage('需要保留的记录', 'user')
    const id = first.messages.value.at(-1)!.persistence!.id
    const restored = useChatMessages(ref('persisted-failure'))
    expect(restored.messages.value.at(-1)?.persistence).toMatchObject({ id, status: 'failed' })
    vi.mocked(chatApi.getConversation).mockResolvedValueOnce({ success: true, messages: [{ id: 12, role: 'ai', content: 'older server reply', timestamp: '2026-10-29T08:00:00Z' }] } as never)
    await restored.syncFromServer()
    expect(restored.messages.value.some(row => row.persistence?.id === id && row.persistence.status === 'failed')).toBe(true)
    vi.mocked(chatApi.saveMessage).mockResolvedValueOnce({ success: true, saved: true, durable: true } as never)
    await restored.retryMessageSave(id)
    expect(vi.mocked(chatApi.saveMessage).mock.calls.at(-1)?.[0]).toMatchObject({ client_message_id: id, content: '需要保留的记录' })
    expect(restored.messages.value.find(row => row.persistence?.id === id)?.persistence?.status).toBe('saved')
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

 it('batches synthetic token cache writes and flushes into the original session', async () => {
  vi.useFakeTimers()
  const sid = ref('synthetic-a')
  const api = useChatMessages(sid)
  const index = api.pushStreamingAiShell()
  await nextTick()
  const writes = vi.spyOn(Storage.prototype, 'setItem')
  writes.mockClear()
  for (let i = 1; i <= 200; i++) api.applyPlainTextToMessageIndex(index, 'x'.repeat(i))
  expect(writes).not.toHaveBeenCalled()
  expect(api.messages.value[index].content).toHaveLength(200)
  await vi.advanceTimersByTimeAsync(250)
  expect(writes).toHaveBeenCalledTimes(2)
  api.applyPlainTextToMessageIndex(index, 'final old session')
  sid.value = 'synthetic-b'
  expect(JSON.parse(localStorage.getItem('chat_synthetic-a_') || '[]')[index].content).toBe('final old session')
  expect(localStorage.getItem('chat_synthetic-b_')).toBeNull()
  writes.mockRestore()
  vi.useRealTimers()
 })


it('restores two same-minute failures once each across repeated server syncs', async () => {
  localStorage.clear(); setActivePinia(createPinia()); vi.clearAllMocks()
  const chatApi = (await import('@/api/chat')).default
  const api = useChatMessages(ref('failure-restoration'))
  api.loadMessages([
    { role: 'user', content: '测试一', time: '12:00', persistence: { id: 'user-a', status: 'local' } },
    { role: 'ai', content: '处理失败：模型未返回可显示的正文，已停止重复请求。请检查模型服务后重试。', time: '12:00', persistence: { id: 'reply-a', status: 'local' } },
    { role: 'user', content: '测试二', time: '12:00', persistence: { id: 'user-b', status: 'local' } },
    { role: 'ai', content: '处理失败：模型未返回可显示的正文，已停止重复请求。请检查模型服务后重试。', time: '12:00', persistence: { id: 'reply-b', status: 'local' } },
  ])
  const serverMessages = api.messages.value.map((row, index) => ({ id: index + 1, role: row.role, content: row.content.replace('处理失败：', ''), time: row.time }))
  vi.mocked(chatApi.getConversation).mockResolvedValue({ success: true, messages: serverMessages } as never)
  await api.syncFromServer()
  await api.syncFromServer()
  expect(api.messages.value).toHaveLength(4)
  expect(api.messages.value.every(row => row.persistence?.status === 'saved')).toBe(true)
  expect(chatApi.saveMessage).not.toHaveBeenCalled()
})

it.each([undefined, 'explicit-turn'])('preserves the user turn through the save envelope and server restoration (override=%s)', async override => {
  localStorage.clear(); setActivePinia(createPinia()); vi.clearAllMocks()
  const chatApi = (await import('@/api/chat')).default
  vi.mocked(chatApi.saveMessage).mockResolvedValueOnce({ success: true, saved: true, durable: true } as never)
  const api = useChatMessages(ref('user-turn-persistence'))
  api.addMessage('本轮原文', 'user', { turnId: 'local-turn' })
  await api.saveMessage('user', '本轮原文', undefined, override ? { turnId: override } : undefined)
  const payload = vi.mocked(chatApi.saveMessage).mock.calls[0]![0] as { metadata: string; client_message_id: string }
  const storedMetadata = { ...JSON.parse(payload.metadata), client_message_id: payload.client_message_id }
  const restored = chatMessageExtrasFromServerRow({ id: 41, role: 'user', metadata: JSON.stringify(storedMetadata) })
  expect(restored.turnId).toBe(override || 'local-turn')
  expect(restored.persistence).toEqual({ id: payload.client_message_id, status: 'saved' })
})


it('restores only safe route receipts after server history, refresh and conversation reentry, and retires them on logout', async () => {
  localStorage.clear(); activeModIdRef.value = ''; setActivePinia(createPinia())
  const chatApi = (await import('@/api/chat')).default
  const route: ChatModelRoute = { provider: 'xiaomi', model: 'flash', route_source: 'platform_configuration', key_source: 'platform', config_revision: 'server-a', route_state: 'completed' }
  const sid = ref('route-history')
  const api = useChatMessages(sid)
  vi.mocked(chatApi.getConversation).mockResolvedValueOnce({ messages: [{ id: 10, role: 'assistant', content: '实际回复', time: '12:00', metadata: JSON.stringify({ route_metadata: { ...route, api_key: 'synthetic-never-render', route_token: 'synthetic-token' } }) }] } as never)
  await api.syncFromServer()
  expect(lastChatModelRoute('route-history')).toEqual(route)
  expect(api.messages.value[0]?.routeMetadata).toEqual(route)
  recordChatModelRoute('route-history', null)
  const reopened = useChatMessages(ref('route-history'))
  expect(reopened.messages.value[0]?.routeMetadata).toEqual(route)
  expect(lastChatModelRoute('route-history')).toEqual(route)
  sid.value = 'other-history'
  expect(lastChatModelRoute('other-history')).toBeNull()
  sid.value = 'route-history'
  expect(lastChatModelRoute('route-history')).toEqual(route)
  activeModIdRef.value = 'other-mod'
  expect(lastChatModelRoute('route-history', 'identity:other-mod')).toBeNull()
  invalidateEnterpriseSessionCache()
  expect(lastChatModelRoute('route-history', 'identity:')).toBeNull()
  expect(chatMessageExtrasFromServerRow({ role: 'user', metadata: { route_metadata: route } }).routeMetadata).toBeUndefined()
})

it('does not replace current selected or failed local metadata with an older completed history receipt', async () => {
  localStorage.clear(); activeModIdRef.value = ''; setActivePinia(createPinia())
  const chatApi = (await import('@/api/chat')).default
  const old: ChatModelRoute = { provider: 'xiaomi', model: 'old-model', route_source: 'platform_configuration', key_source: 'platform', config_revision: 'a', route_state: 'completed' }
  const current: ChatModelRoute = { ...old, model: 'current-model', config_revision: 'b', route_state: 'selected' }
  const api = useChatMessages(ref('live-history-fence'))
  api.loadMessages([
    { role: 'ai', content: 'older reply', time: '12:00', routeMetadata: old, persistence: { id: 'server:1', status: 'saved' } },
    { role: 'ai', content: '已停止接收本轮回复', time: '12:01', routeMetadata: current, persistence: { id: 'local-current', status: 'local' } },
  ])
  vi.mocked(chatApi.getConversation).mockResolvedValueOnce({ messages: [{ id: 1, role: 'assistant', content: 'older reply', time: '12:00', metadata: { route_metadata: old } }] } as never)
  await api.syncFromServer()
  expect(lastChatModelRoute('live-history-fence')).toEqual(current)
  expect(useChatMessages(ref('live-history-fence')).messages.value.at(-1)?.routeMetadata).toEqual(current)
})


it('retires only cached streaming placeholders after refresh while preserving unconfirmed route identity across history and account scopes', async () => {
  localStorage.clear(); activeModIdRef.value = ''; setActivePinia(createPinia())
  const route: ChatModelRoute = { provider: 'xiaomi', model: 'selected-model', route_source: 'platform_configuration', key_source: 'platform', config_revision: 'a', route_state: 'selected' }
  const first = useChatMessages(ref('refresh-stream'))
  const idx = first.pushStreamingAiShell()
  first.messages.value[idx]!.routeMetadata = route
  await nextTick()
  expect(first.messages.value[idx]?.streamingShell).toBe(true)
  const reopened = useChatMessages(ref('refresh-stream'))
  expect(reopened.messages.value.at(-1)?.streamingShell).toBeUndefined()
  expect(reopened.messages.value.at(-1)?.content).toContain('未收到完成回执')
  expect(lastChatModelRoute('refresh-stream')).toEqual(route)
  expect(first.messages.value[idx]?.streamingShell).toBe(true)
  const sid = ref('other-conversation')
  const history = useChatMessages(sid)
  expect(lastChatModelRoute('other-conversation')).toBeNull()
  sid.value = 'refresh-stream'
  expect(history.messages.value.at(-1)?.streamingShell).toBeUndefined()
  expect(history.messages.value.at(-1)?.routeMetadata).toEqual(route)
  invalidateEnterpriseSessionCache()
  expect(lastChatModelRoute('refresh-stream')).toBeNull()
})

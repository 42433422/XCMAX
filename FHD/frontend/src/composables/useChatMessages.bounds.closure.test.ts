import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref, type EffectScope } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { CHAT_CACHE_BYTES, CHAT_CACHE_MESSAGES, CHAT_RESIDENT_BYTES, CHAT_RESIDENT_MESSAGES, chatMessageExtrasFromServerRow,
  resetChatMessageStores, useChatMessages, type ChatMessage } from './useChatMessages'

const { getConversation } = vi.hoisted(() => ({ getConversation: vi.fn() }))
vi.mock('@/api/chat', () => ({ default: { getConversation, saveMessage: vi.fn() } }))
vi.mock('@/stores/mods', async () => {
  const { ref } = await import('vue')
  const activeModId = ref('')
  return { useModsStore: () => ({ activeModId, $id: 'mods' }) }
})
vi.mock('@/stores/industry', () => ({ useIndustryStore: () => ({ currentIndustryId: '通用' }) }))
vi.mock('@/constants/industryPresets', () => ({ getIndustryWelcomeMarkdown: () => '您好！我是您的助手' }))
vi.mock('@/utils/chatStorageKeys', () => ({
  resolveChatIdentity: () => 'owner', resolveChatStorageScope: () => 'owner',
  buildChatMessagesKey: (sid: string) => `chat_${sid}`, buildChatSessionMetaKey: (sid: string) => `meta_${sid}`,
}))
vi.mock('@/utils/tts', () => ({ speakText: vi.fn(), stopSpeaking: vi.fn(), cleanTextForSpeech: (text: string) => text }))

type ServerRow = { id: number; role: string; content: string; metadata?: string }
let rows: ServerRow[]
const scopes: EffectScope[] = []
const ids = (messages: ChatMessage[]) => messages.map(message => message.serverMessageId ?? Number(message.persistence?.id?.replace('server:', '')))
const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length
const saved = (id: number, extras: Partial<ChatMessage> = {}): ChatMessage => ({
  role: 'ai', content: `message ${id}`, time: '10:00', serverMessageId: id,
  persistence: { id: `server:${id}`, status: 'saved', durable: true }, ...extras,
})
function fixture(sid = ref('bounded')) {
  const scope = effectScope()
  scopes.push(scope)
  return { scope, chat: scope.run(() => useChatMessages(sid))! }
}
beforeEach(() => {
  setActivePinia(createPinia())
  resetChatMessageStores()
  localStorage.clear()
  rows = Array.from({ length: 650 }, (_, index) => ({ id: index + 1, role: 'ai', content: `message ${index + 1}` }))
  getConversation.mockReset().mockImplementation(async (sid, params = {}) => {
    const eligible = rows.filter(row => (!params.before_id || row.id < params.before_id)
      && (!params.after_id || row.id > params.after_id) && (!params.through_id || row.id <= params.through_id))
    const limit = params.limit || 50
    const messages = params.after_id ? eligible.slice(0, limit) : eligible.slice(-limit)
    return { success: true, durable: true, id: sid, revision: 0, messages,
      snapshot_latest_id: rows.at(-1)?.id, has_more: eligible.length > limit,
      next_before_id: !params.after_id && eligible.length > limit ? messages[0].id : null }
  })
})
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); resetChatMessageStores(); localStorage.clear() })

describe('durable history window', () => {
  it.each(['created', 'claimed', 'blocked', 'pending', 'accepted', 'needs_verification', 'inconclusive'])(
    'pins acknowledged %s observations and applies backpressure until they settle', status => {
    const { chat } = fixture()
    const pending = Array.from({ length: CHAT_RESIDENT_MESSAGES }, (_, index) => saved(index + 1,
      chatMessageExtrasFromServerRow({ id: index + 1, durable: true, role: 'ai', metadata: { summary: { status } } })))
    chat.loadMessages([...pending, ...Array.from({ length: 200 }, (_, index) => saved(index + 1000))])
    for (let id = 1; id <= CHAT_RESIDENT_MESSAGES; id++) expect(ids(chat.messages.value)).toContain(id)
    expect(() => chat.assertHistoryCapacity()).toThrow('待保存或待处理')
  })

  it.each(['rejected', 'cancelled', 'succeeded', 'completed', 'failed', 'timed_out'])(
    'allows acknowledged %s history to leave the window', status => {
    const { chat } = fixture()
    chat.loadMessages([saved(1, { workflowAction: status, agentRunTrace: {
      run_id: 'settled', intent: '', status: 'blocked', terminal: true, phases: [],
    } }), ...Array.from({ length: 200 }, (_, index) => saved(index + 1000))])
    expect(ids(chat.messages.value)).not.toContain(1)
    expect(() => chat.assertHistoryCapacity()).not.toThrow()
  })

  it('visits every SQL row in both directions with bounded resident data and bootstrap writes', async () => {
    const { chat } = fixture()
    await chat.syncFromServer({ required: true })
    const backward = new Set(ids(chat.messages.value))
    for (let page = 0; chat.messagesHaveEarlier.value && page < 20; page++) {
      await chat.loadEarlierMessages()
      ids(chat.messages.value).forEach(id => backward.add(id))
      expect(chat.messages.value.length).toBeLessThanOrEqual(CHAT_RESIDENT_MESSAGES)
      expect(JSON.parse(localStorage.getItem('chat_bounded')!).length).toBeLessThanOrEqual(CHAT_CACHE_MESSAGES)
    }
    expect(backward.size).toBe(rows.length)
    expect(chat.messagesHaveEarlier.value).toBe(false)
    const forward = new Set(ids(chat.messages.value))
    for (let page = 0; chat.messagesHaveLater.value && page < 20; page++) {
      await chat.loadNewerMessages()
      ids(chat.messages.value).forEach(id => forward.add(id))
      expect(chat.messages.value.length).toBeLessThanOrEqual(CHAT_RESIDENT_MESSAGES)
    }
    expect(forward.size).toBe(rows.length)
    expect(chat.messagesHaveLater.value).toBe(false)
    expect(getConversation.mock.calls.slice(1).every(([, params]) => params.through_id === 650)).toBe(true)
  })

  it('does not skip neighbors of oversized rows and never writes those rows to localStorage', async () => {
    rows = Array.from({ length: 30 }, (_, index) => ({ id: index + 1, role: 'ai', content: 'x'.repeat(32 * 1024) }))
    rows.push({ id: 31, role: 'ai', content: 'x'.repeat(CHAT_RESIDENT_BYTES + 1024) })
    const { chat } = fixture()
    await chat.syncFromServer({ required: true })
    expect(ids(chat.messages.value)).toEqual([31])
    const visited = new Set(ids(chat.messages.value))
    for (let page = 0; chat.messagesHaveEarlier.value && page < 10; page++) {
      await chat.loadEarlierMessages()
      ids(chat.messages.value).forEach(id => visited.add(id))
      expect(bytes(chat.messages.value)).toBeLessThanOrEqual(CHAT_RESIDENT_BYTES)
      expect(bytes(JSON.parse(localStorage.getItem('chat_bounded')!))).toBeLessThanOrEqual(CHAT_CACHE_BYTES)
    }
    expect(visited.size).toBe(31)
    visited.clear()
    ids(chat.messages.value).forEach(id => visited.add(id))
    for (let page = 0; chat.messagesHaveLater.value && page < 10; page++) {
      await chat.loadNewerMessages()
      ids(chat.messages.value).forEach(id => visited.add(id))
    }
    expect(visited.size).toBe(31)
    expect(chat.messages.value[0].content).toBe(rows[30].content)
    expect(localStorage.getItem('chat_bounded')).toBe('[]')
    resetChatMessageStores()
    const reopened = fixture().chat
    await reopened.syncFromServer({ required: true })
    expect(reopened.messages.value[0].content).toBe(rows[30].content)
    expect(localStorage.getItem('chat_bounded')).toBe('[]')
  })

  it('keeps an older snapshot stable when new rows arrive, then loads the actual latest context', async () => {
    const { chat } = fixture()
    await chat.syncFromServer({ required: true })
    await chat.loadEarlierMessages()
    await chat.loadEarlierMessages()
    const before = ids(chat.messages.value)
    rows.push({ id: 651, role: 'ai', content: 'new unseen reply' })
    await chat.syncFromServer()
    expect(ids(chat.messages.value)).toEqual(before)
    expect(chat.messagesHaveLater.value).toBe(true)
    await chat.loadLatestMessages()
    expect(ids(chat.messages.value).at(-1)).toBe(651)
    expect(chat.messagesHaveLater.value).toBe(false)
  })

  it('pins pending saves, approvals, streams and uncertain outcomes instead of silently trimming them', async () => {
    const { chat } = fixture()
    const protectedRows = [
      saved(1, { approvalCard: { status: 'pending', run_id: 'approval' } }),
      saved(2, { runtimeContinuation: { runId: 'waiting', status: 'waiting_user', sessionId: 'bounded' } }),
      saved(3, { streamStatus: 'streaming' }),
      saved(4, { execution: { idempotencyKey: 'unknown', intent: 'write', committed: false, effect: 'partial', outcome: 'unknown' } }),
      saved(5, { persistence: { id: 'retry', status: 'failed', request: { role: 'ai', content: 'unsaved receipt' } } }),
    ]
    chat.loadMessages([...protectedRows, ...Array.from({ length: 300 }, (_, i) => saved(i + 100))])
    expect(ids(chat.messages.value).slice(0, 5)).toEqual([1, 2, 3, 4, 5])
    expect(chat.messages.value.length).toBe(CHAT_RESIDENT_MESSAGES + protectedRows.length)
    expect(chat.messages.value.find(message => message.serverMessageId === 4)?.execution?.outcome).toBe('unknown')
    const second = fixture().chat
    expect(second.messages.value).toBe(chat.messages.value)
    expect(second.messagesHaveEarlier.value).toBe(true)
    await chat.loadLatestMessages()
    expect(ids(chat.messages.value).slice(0, 5)).toEqual([1, 2, 3, 4, 5])
    expect(chat.messages.value.find(message => message.serverMessageId === 5)?.persistence?.request?.content).toBe('unsaved receipt')
    chat.loadMessages(Array.from({ length: CHAT_RESIDENT_MESSAGES }, (_, i) => saved(i + 1, {
      persistence: { id: `pending:${i}`, status: 'failed', request: { role: 'ai', content: 'receipt' } },
    })), { revision: 0, has_more: true, next_before_id: 1 })
    expect(() => chat.assertHistoryCapacity()).toThrow('待保存或待处理')
    getConversation.mockClear()
    await chat.loadEarlierMessages()
    expect(getConversation).not.toHaveBeenCalled()
    expect(chat.messages.value).toHaveLength(CHAT_RESIDENT_MESSAGES)
  })

  it('does not shift the retained streaming index and compacts acknowledged history after release', () => {
    const { chat } = fixture()
    chat.loadMessages(Array.from({ length: 200 }, (_, i) => saved(i + 1)))
    const retained = chat.retainConversationMessages()
    const index = retained.pushStreamingAiShell()
    const shell = retained.messages.value[index]
    retained.messages.value.push(...Array.from({ length: 20 }, (_, i) => saved(501 + i)))
    retained.persist()
    retained.applyPlainTextToMessageIndex(index, 'the original stream')
    expect(retained.messages.value[index]).toBe(shell)
    expect(shell.content).toBe('the original stream')
    shell.persistence = { id: 'server:500', status: 'saved', durable: true }
    shell.serverMessageId = 500
    retained.release()
    expect(chat.messages.value).toHaveLength(CHAT_RESIDENT_MESSAGES)
    expect(chat.messages.value.find(message => message.serverMessageId === 500)?.content).toBe('the original stream')
    expect(ids(chat.messages.value).at(-1)).toBe(520)
  })

  it('retires pending pagination on dispose without writing late rows into shared history', async () => {
    const { chat, scope } = fixture()
    await chat.syncFromServer({ required: true })
    let resolve!: (value: unknown) => void
    getConversation.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const before = ids(chat.messages.value)
    const pending = chat.loadEarlierMessages()
    const other = fixture().chat
    scope.stop()
    resolve({ success: true, revision: 0, has_more: false, messages: [{ id: 1, role: 'ai', content: 'late' }] })
    await pending
    await nextTick()
    expect(ids(chat.messages.value)).toEqual(before)
    expect(other.earlierMessagesLoading.value).toBe(false)
  })

  it.each([1, null])('retains an unconfirmed save after revision %s without rebasing or replaying it', async revision => {
    const { chat } = fixture()
    chat.loadMessages([saved(1, { role: 'user', turnId: 'original-turn', persistence: {
      id: 'pending-original', status: 'failed', request: { role: 'user', content: 'original request', expected_revision: 0 },
    } })])
    getConversation.mockResolvedValueOnce({ success: true, id: 'bounded', revision, durable: true,
      messages: revision === null ? [] : [{ id: 100, role: 'ai', content: 'current history' }], has_more: false, snapshot_latest_id: 100 })
    await chat.loadLatestMessages()
    const pending = chat.messages.value.find(message => message.persistence?.id === 'pending-original')
    expect(pending?.persistence?.request?.expected_revision).toBe(0)
    expect(pending?.persistence?.request?.content).toBe('original request')
    expect(pending?.persistence?.error).toContain('原会话')
  })
})

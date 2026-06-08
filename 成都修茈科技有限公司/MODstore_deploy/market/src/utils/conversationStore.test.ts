import { beforeEach, describe, expect, it } from 'vitest'
import {
  createConversation,
  exportConversationAsMarkdown,
  loadActiveId,
  loadConversations,
  makeMessage,
  saveActiveId,
  saveConversations,
  searchConversations,
  summarizeForTitle,
  buildConversationTitle,
  shouldReloadConversationFromStorage,
  mergeConversationsForPick,
} from './conversationStore'

describe('conversationStore', () => {
  beforeEach(() => {
    if (typeof localStorage !== 'undefined') localStorage.clear()
  })

  it('creates conversation with default title and messages array', () => {
    const c = createConversation()
    expect(c.id).toMatch(/^conv_/)
    expect(c.title).toBe('新对话')
    expect(Array.isArray(c.messages)).toBe(true)
    expect(c.pinned).toBe(false)
  })

  it('summarizeForTitle truncates and trims', () => {
    expect(summarizeForTitle('  hello  ')).toBe('hello')
    expect(summarizeForTitle('a'.repeat(100)).length).toBeLessThanOrEqual(29)
    expect(summarizeForTitle('')).toBe('新对话')
  })

  it('buildConversationTitle keeps more context for storage', () => {
    expect(buildConversationTitle('remember code zebra reply ok')).toBe('remember code zebra reply ok')
    expect(buildConversationTitle('a'.repeat(80)).length).toBeLessThanOrEqual(49)
  })

  it('persists and reloads conversations sorted by pinned + updatedAt', () => {
    const a = createConversation({ title: 'A' })
    a.updatedAt = 1000
    const b = createConversation({ title: 'B' })
    b.updatedAt = 2000
    const c = createConversation({ title: 'C' })
    c.updatedAt = 500
    c.pinned = true
    saveConversations([a, b, c])

    const restored = loadConversations()
    expect(restored.map((x) => x.title)).toEqual(['C', 'B', 'A'])
  })

  it('saves and loads active id', () => {
    saveActiveId('abc')
    expect(loadActiveId()).toBe('abc')
  })

  it('searchConversations matches title and message body', () => {
    const a = createConversation({ title: '门店日报方案' })
    a.messages.push(makeMessage('user', '帮我写一份周报'))
    const b = createConversation({ title: '其它' })
    b.messages.push(makeMessage('user', '联网搜索股价'))
    expect(searchConversations([a, b], '日报').length).toBe(1)
    expect(searchConversations([a, b], '周报').length).toBe(1)
    expect(searchConversations([a, b], '股价').length).toBe(1)
    expect(searchConversations([a, b], '不存在').length).toBe(0)
  })

  it('exports conversation to markdown with header', () => {
    const c = createConversation({ title: '测试' })
    c.messages.push(makeMessage('user', '问题'))
    c.messages.push(makeMessage('assistant', '回答'))
    const md = exportConversationAsMarkdown(c)
    expect(md).toContain('# 测试')
    expect(md).toContain('问题')
    expect(md).toContain('回答')
  })

  it('shouldReloadConversationFromStorage when UI empty but storage has messages', () => {
    const msg = makeMessage('user', 'remember code zebra')
    expect(shouldReloadConversationFromStorage(0, [msg])).toBe(true)
    expect(shouldReloadConversationFromStorage(1, [msg])).toBe(false)
    expect(shouldReloadConversationFromStorage(0, [])).toBe(false)
  })

  it('mergeConversationsForPick prefers storage when memory messages empty', () => {
    const id = 'conv_test'
    const memory = [{ ...createConversation(), id, messages: [] }]
    const stored = createConversation({ title: '历史' })
    stored.id = id
    stored.messages.push(makeMessage('user', 'hello'), makeMessage('assistant', 'hi'))
    const merged = mergeConversationsForPick(memory, [stored], id, 0)
    expect(merged.find((c) => c.id === id)?.messages.length).toBe(2)
  })

  it('simulates sidebar pick: persist then hydrate empty UI', () => {
    const c = createConversation({ title: 'remember code zebra' })
    c.messages.push(makeMessage('user', 'remember code zebra'), makeMessage('assistant', 'ok'))
    saveConversations([c])
    saveActiveId(c.id)
    const memoryList: typeof c[] = [{ ...c, messages: [] }]
    const storageList = loadConversations()
    const uiCount = 0
    const hydrated = mergeConversationsForPick(memoryList, storageList, c.id, uiCount)
    expect(hydrated.find((x) => x.id === c.id)?.messages.map((m) => m.role)).toEqual(['user', 'assistant'])
  })

  it('caps stored conversations to 100 entries', () => {
    const list = Array.from({ length: 130 }, (_, i) => {
      const c = createConversation({ title: `T${i}` })
      c.updatedAt = i
      return c
    })
    saveConversations(list)
    const restored = loadConversations()
    expect(restored.length).toBe(100)
  })
})

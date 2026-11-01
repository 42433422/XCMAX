import { describe, expect, it } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { buildLocalProactiveSuggestions, proactiveReplyMessageId, PROACTIVE_SUGGESTIONS_STORAGE_KEY, useProactiveReplySuggestions } from './useProactiveReplySuggestions'

describe('buildLocalProactiveSuggestions', () => {
  it('returns exactly three suggestions', () => {
    const items = buildLocalProactiveSuggestions([
      { role: 'user', content: '帮我开单' },
      { role: 'assistant', content: '可以，先确认客户信息' },
    ])
    expect(items).toHaveLength(3)
    expect(items.every((i) => i.text.trim().length > 0)).toBe(true)
  })

  it('uses excel-oriented copy when dialogue mentions import', () => {
    const items = buildLocalProactiveSuggestions([
      { role: 'assistant', content: 'Excel 映射已完成，可以导入' },
    ])
    expect(items.some((i) => /导入|映射|预览|写入/.test(i.text))).toBe(true)
  })

  it('exports an isolated storage key distinct from WeChat star refresh', () => {
    expect(PROACTIVE_SUGGESTIONS_STORAGE_KEY).toBe('xcagi_proactive_suggestions')
    expect(PROACTIVE_SUGGESTIONS_STORAGE_KEY).not.toContain('wechat')
  })

  it('waits for a completed reply, fills only the draft, and clears on session change', async () => {
    const scope = effectScope()
    const enabled = ref(true), isLoading = ref(true), scopeKey = ref('session-1')
    const messageInput = ref('')
    const api = scope.run(() => useProactiveReplySuggestions({
      messages: ref([{ role: 'assistant', content: '请核对订单' }]),
      messageInput, enabled, isLoading, scopeKey,
    }))!
    try {
      expect(api.proactiveSuggestions.value).toHaveLength(0)
      isLoading.value = false
      await nextTick()
      expect(api.proactiveSuggestions.value).toHaveLength(3)
      const choice = api.proactiveSuggestions.value[0]!
      api.pickProactiveSuggestion(choice)
      expect(messageInput.value).not.toBe('')
      scopeKey.value = 'session-2'
      expect(api.proactiveSuggestions.value).toHaveLength(0)
      enabled.value = false
      await nextTick()
      const draft = messageInput.value
      api.pickProactiveSuggestion(choice)
      expect(messageInput.value).toBe(draft)
    } finally { scope.stop() }
  })

  it('keeps each completed reply attached to its own context while the next reply streams', () => {
    const scope = effectScope()
    const messages = ref([
      { role: 'user', content: '帮我开单' },
      { role: 'ai', content: '请核对客户', persistence: { id: 'order-reply' } },
      { role: 'user', content: '接下来导入 Excel' },
      { role: 'ai', content: '正在整理映射', persistence: { id: 'excel-reply' } },
    ])
    const isLoading = ref(false), isStreamingReply = ref(true)
    const api = scope.run(() => useProactiveReplySuggestions({
      messages, messageInput: ref(''), enabled: ref(true), isLoading, isStreamingReply, scopeKey: ref('a'),
    }))!
    try {
      const firstId = proactiveReplyMessageId(messages.value[1]!)
      const latestId = proactiveReplyMessageId(messages.value[3]!)
      expect(api.proactiveSuggestionsByMessage.value.get(firstId)?.map(item => item.text).join()).toContain('客户')
      expect(api.proactiveSuggestionsByMessage.value.has(latestId)).toBe(false)
      const streamingMap = api.proactiveSuggestionsByMessage.value
      const oldChoice = api.proactiveSuggestionsByMessage.value.get(firstId)![0]
      messages.value[3]!.content += '，仍在流式输出'
      expect(api.proactiveSuggestionsByMessage.value).toBe(streamingMap)
      expect(api.proactiveSuggestionsByMessage.value.get(firstId)![0]).toBe(oldChoice)
      isStreamingReply.value = false
      const current = api.proactiveSuggestionsByMessage.value.get(latestId)!
      expect(current).toHaveLength(3)
      expect(current.map(item => item.text).join()).toContain('映射')
      expect(current.every(item => item.messageId === latestId && item.scopeKey === 'a')).toBe(true)
    } finally { scope.stop() }
  })

  it('rejects old choices and late old-array updates until the new session history replaces it', async () => {
    const scope = effectScope()
    const messages = ref([{ role: 'ai', content: '请核对订单', persistence: { id: 'shared-id' } }])
    const scopeKey = ref('a'), messageInput = ref('原草稿'), isLoading = ref(false)
    const api = scope.run(() => useProactiveReplySuggestions({ messages, messageInput, scopeKey, isLoading, enabled: ref(true) }))!
    try {
      const old = api.proactiveSuggestions.value[0]!
      scopeKey.value = 'b'
      expect(api.proactiveSuggestions.value).toEqual([])
      messages.value[0]!.content = '旧会话迟到结果'
      isLoading.value = true
      isLoading.value = false
      await nextTick()
      expect(api.proactiveSuggestions.value).toEqual([])
      api.pickProactiveSuggestion(old)
      expect(messageInput.value).toBe('原草稿')
      messages.value = [{ role: 'ai', content: 'Excel 映射完成', persistence: { id: 'shared-id' } }]
      await nextTick()
      api.pickProactiveSuggestion(old)
      expect(messageInput.value).toBe('原草稿')
      const current = api.proactiveSuggestions.value[0]!
      api.pickProactiveSuggestion(current)
      expect(messageInput.value).toBe(`原草稿\n${current.text}`)
    } finally { scope.stop() }
  })

  it('restores historical replies by identity and retires a replaced reply choice', () => {
    const scope = effectScope()
    const messages = ref([{ role: 'ai', content: '确认订单', persistence: { id: 'reply' } }])
    const messageInput = ref('')
    const api = scope.run(() => useProactiveReplySuggestions({ messages, messageInput, enabled: ref(true), scopeKey: ref('history') }))!
    try {
      const old = api.proactiveSuggestions.value[0]!
      messages.value = [{ role: 'ai', content: 'Excel 导入完成', persistence: { id: 'reply' } }]
      expect(api.proactiveSuggestions.value).toHaveLength(3)
      expect(api.proactiveSuggestions.value[0]!.messageId).toBe(old.messageId)
      api.pickProactiveSuggestion(old)
      expect(messageInput.value).toBe('')
      expect(proactiveReplyMessageId({ role: 'ai', content: '相同回复' })).not.toBe(proactiveReplyMessageId({ role: 'ai', content: '相同回复' }))
    } finally { scope.stop() }
  })
})


it('does not suggest summaries or continuations for failed replies', () => {
  expect(buildLocalProactiveSuggestions([{ role: 'user', content: '你好' }, { role: 'ai', content: '处理失败：模型未返回可显示的正文' }])).toEqual([])
  expect(buildLocalProactiveSuggestions([{ role: 'ai', content: '服务不可达', workflowAction: 'failed' }])).toEqual([])
})

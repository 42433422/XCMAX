import { describe, expect, it } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { buildLocalProactiveSuggestions, PROACTIVE_SUGGESTIONS_STORAGE_KEY, useProactiveReplySuggestions } from './useProactiveReplySuggestions'

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
      api.pickProactiveSuggestion(api.proactiveSuggestions.value[0]!)
      expect(messageInput.value).not.toBe('')
      scopeKey.value = 'session-2'
      expect(api.proactiveSuggestions.value).toHaveLength(0)
      enabled.value = false
      await nextTick()
      const draft = messageInput.value
      api.pickProactiveSuggestion('disabled choice')
      expect(messageInput.value).toBe(draft)
    } finally { scope.stop() }
  })
})

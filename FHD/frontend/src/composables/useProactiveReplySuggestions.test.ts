import { describe, expect, it } from 'vitest'
import { buildLocalProactiveSuggestions, PROACTIVE_SUGGESTIONS_STORAGE_KEY } from './useProactiveReplySuggestions'

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
})

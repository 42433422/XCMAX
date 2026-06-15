import { describe, expect, it } from 'vitest'
import {
  extractToolInvocationChips,
  formatToolInvocationChip,
  hasVisibleChatBubbleBody,
  stripPlannerDisplayMarkers,
  stripToolInvocationLeaks,
  tryParseToolInvocationJson,
} from './chatBubbleDisplay'

describe('chatBubbleDisplay', () => {
  it('parses excel read tool json', () => {
    const raw = '{"file_path": "uploads/xcagi-quickstart-sample-b.xlsx", "action": "read"}'
    const obj = tryParseToolInvocationJson(raw)
    expect(obj?.file_path).toBe('uploads/xcagi-quickstart-sample-b.xlsx')
    expect(formatToolInvocationChip(obj!)).toEqual({
      label: '读取',
      detail: 'xcagi-quickstart-sample-b.xlsx',
    })
  })

  it('strips leaked tool json from bubble body', () => {
    const raw = '{"file_path": "uploads/xcagi-quickstart-sample-b.xlsx", "action": "read"}'
    expect(stripToolInvocationLeaks(raw)).toBe('')
    expect(hasVisibleChatBubbleBody(raw)).toBe(false)
  })

  it('keeps normal prose while removing tool json lines', () => {
    const raw = [
      '{"file_path": "uploads/a.xlsx", "action": "read"}',
      '已读取完成，请确认是否入库。',
    ].join('\n')
    expect(stripToolInvocationLeaks(raw)).toBe('已读取完成，请确认是否入库。')
    expect(extractToolInvocationChips(raw)).toEqual([{ label: '读取', detail: 'a.xlsx' }])
  })

  it('ignores non-tool json', () => {
    const raw = '{"name": "张三", "age": 18}'
    expect(tryParseToolInvocationJson(raw)).toBeNull()
    expect(stripToolInvocationLeaks(raw)).toBe(raw)
  })

  it('strips html-entity encoded tool json from bubble body', () => {
    const raw = '{&quot;file_path&quot;: &quot;uploads/a.xlsx&quot;, &quot;action&quot;: &quot;read&quot;}'
    expect(hasVisibleChatBubbleBody(raw)).toBe(false)
    expect(extractToolInvocationChips(raw)).toEqual([{ label: '读取', detail: 'a.xlsx' }])
  })

  it('strips planner display markers', () => {
    const raw = '摘要 [正在调用工具:excel.read] 正文'
    const stripped = stripPlannerDisplayMarkers(raw)
    expect(stripped).not.toContain('[正在调用工具')
    expect(stripped).toContain('摘要')
    expect(stripped).toContain('正文')
    expect(hasVisibleChatBubbleBody(raw)).toBe(true)
  })

  it('treats streaming placeholder dots as invisible body', () => {
    expect(hasVisibleChatBubbleBody('...')).toBe(false)
    expect(hasVisibleChatBubbleBody('…')).toBe(false)
  })

  it('strips fullwidth planner tool markers', () => {
    const raw = '结果【正在调用工具:excel.read】完成'
    expect(stripPlannerDisplayMarkers(raw)).not.toContain('【正在调用工具')
    expect(stripPlannerDisplayMarkers(raw)).toContain('结果')
  })
})

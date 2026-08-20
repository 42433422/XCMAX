import { describe, expect, it } from 'vitest'
import { formatChatMessageTime, formatHistoryTime, formatTaskSourceLabel, formatTaskTime, normalizeTaskDisplayText } from './chatTaskLabels'

describe('chatTaskLabels', () => {
  it('formatTaskTime returns empty for falsy ts', () => {
    expect(formatTaskTime(0)).toBe('')
  })

  it('formatTaskTime formats zh-CN clock', () => {
    const label = formatTaskTime(new Date('2026-06-14T08:30:00').getTime())
    expect(label).toMatch(/\d{1,2}:\d{2}/)
  })

  it('formatTaskSourceLabel maps known sources', () => {
    expect(formatTaskSourceLabel('workflow')).toBe('工作流')
    expect(formatTaskSourceLabel('wechat')).toBe('微信')
    expect(formatTaskSourceLabel('agent')).toBe('智能执行')
    expect(formatTaskSourceLabel('unknown-src')).toBe('unknown-src')
    expect(formatTaskSourceLabel('')).toBe('—')
  })

  it('preserves a server message timestamp instead of replacing it with now', () => {
    const raw = '2026-07-13T10:25:00-07:00'
    expect(formatChatMessageTime(raw)).toBe(new Date(raw).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }))
    expect(formatChatMessageTime('07:25')).toBe('07:25')
  })

  it('shows date in history labels', () => {
    const now = new Date('2026-07-13T12:00:00').getTime()
    expect(formatHistoryTime('2026-07-13T08:30:00', now)).toContain('今天')
    expect(formatHistoryTime('2026-07-12T08:30:00', now)).toContain('7月12日')
  })

  it('removes internal legacy and agent terminology from task text', () => {
    expect(normalizeTaskDisplayText('Agent Progress 100% Legacy planner run 执行完成')).toBe('执行进度 100% 智能任务 执行完成')
    expect(normalizeTaskDisplayText('等待 Agent 事件')).toBe('等待执行状态')
  })
})

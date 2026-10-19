import { describe, expect, it } from 'vitest'
import {
  auditItems, buildTimeline, formatBeijingTime, parseServerTime, resolutionStateBadge, runStatusBadge, submitterTypeLabel, ticketStatusBadge, yesNoBadge,
} from '../../../admin-console/src/utils/customerServiceTicketFormat'

describe('customer service ticket formatting', () => {
  it('treats zone-less server times as UTC and renders Beijing time', () => {
    expect(formatBeijingTime('2026-10-16T04:41:57.835690')).toBe('2026-10-16 12:41:57')
    expect(formatBeijingTime('2026-10-16 16:00:00')).toBe('2026-10-17 00:00:00')
    expect(formatBeijingTime('2026-10-16T04:48:46+00:00')).toBe('2026-10-16 12:48:46')
    expect(formatBeijingTime('2026-10-16T12:48:46+08:00')).toBe('2026-10-16 12:48:46')
    expect(formatBeijingTime('')).toBe('—')
    expect(formatBeijingTime(null, '未关闭')).toBe('未关闭')
    expect(formatBeijingTime('garbage')).toBe('garbage')
    expect(parseServerTime('garbage')).toBeNull()
  })
  it('maps statuses to Chinese labels and tones without inventing meaning for unknown keys', () => {
    expect(ticketStatusBadge({ status: 'resolved', lifecycle_label: '已完成' })).toEqual({ label: '已完成', tone: 'success', raw: 'resolved' })
    expect(ticketStatusBadge({ status: 'processing' })).toMatchObject({ label: '处理中', tone: 'info' })
    expect(ticketStatusBadge({ status: 'mystery', lifecycle_label: '待补充' })).toMatchObject({ label: '待补充', tone: 'warning' })
    expect(ticketStatusBadge({})).toMatchObject({ label: '未记录', tone: 'neutral' })
    expect(runStatusBadge('failed')).toMatchObject({ label: '失败', tone: 'danger' })
    expect(runStatusBadge('weird')).toMatchObject({ label: 'weird', tone: 'warning' })
    expect(resolutionStateBadge('repair_failed')).toMatchObject({ label: '修复未完成', tone: 'danger' })
    expect(yesNoBadge(undefined, '是', '否')).toMatchObject({ label: '未记录' })
    expect(yesNoBadge(true, '是', '否')).toMatchObject({ label: '是', tone: 'success' })
    expect(submitterTypeLabel('admin')).toBe('管理员提交')
    expect(submitterTypeLabel('customer')).toBe('客户提交')
    expect(submitterTypeLabel('unknown')).toBe('提交人待确认')
  })
  it('orders timeline items by time and puts undated ones last', () => {
    const items = buildTimeline(
      [{ id: 2, decision: 'accepted', created_at: '2026-10-16T05:00:00', confidence: null }],
      [{ id: 1, action_type: 'custom.thing', status: 'running', error: '超时', created_at: '2026-10-16T04:00:00' }],
      { customer_decisions: [{ decision: 'resolved' }, { decision: 'other', at: '2026-10-16T06:00:00Z' }], employee_reports: 'not-a-list' },
    )
    expect(items.map(i => i.key)).toEqual(['action-1', 'decision-2', 'customer-1', 'customer-0'])
    expect(items[0]).toMatchObject({ title: '动作 #1 · custom.thing', text: '超时' })
    expect(items[1].badges.map(b => b.label)).toEqual(['已受理', '未记录'])
    expect(items[2].title).toBe('客户操作：other')
    expect(items[3].title).toBe('客户确认已解决')
  })
  it('summarises audit rows from detail or detail_json', () => {
    const [a, b] = auditItems([
      { id: 1, actor_type: 'system', event_type: 'employee_progress', detail_json: { progress: 'x'.repeat(300) }, created_at: '2026-10-16T04:48:46' },
      { actor_type: 'admin', user_id: 5, event_type: 'decision_made', detail: { decision: 'rejected' } },
    ])
    expect(a).toMatchObject({ id: '1', actor: '系统', event: '员工处理进展', at: '2026-10-16 12:48:46' })
    expect(a.summary.endsWith('…')).toBe(true)
    expect(b).toMatchObject({ id: '—', actor: '管理员 · 用户 ID 5', event: 'AI 受理决策', summary: '决策：已拒绝', at: '—' })
  })
})

import { describe, expect, it } from 'vitest'
import {
  auditItems, buildTimeline, executionOverview, formatBeijingTime, parseServerTime, resolutionStateBadge, runStatusBadge, submitterTypeLabel, teamMembers, ticketStatusBadge, yesNoBadge,
} from '../../../admin-console/src/utils/customerServiceTicketFormat'

describe('customer service ticket formatting', () => {
  it('does not turn assignment, an absent task id or unknown results into accepted work', () => {
    expect(executionOverview(undefined)).toBeNull()
    const overview = executionOverview({ receipts: [
      { state: 'requested', accepted: false, role: 'fix' },
      { state: 'accepted', accepted: true, task_id: '' },
      { state: 'unknown', accepted: true, task_id: 'await-result', requires_reconciliation: true },
      { state: 'completed', accepted: true, task_id: 'done-task', completed: true },
    ] })!
    expect(overview.receipts.map(row => row.badge.label)).toEqual([
      '尚无真实接单凭证', '尚无真实接单凭证', '接单结果待对账', '已接单并完成',
    ])
    expect(overview.progressAt).toBe('时间未记录')
    expect(overview.workOrder).toBe('未关联产品工作单')
  })
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
    expect(resolutionStateBadge('resolved', 'admin_runtime')).toMatchObject({ label: '管理员验收已关闭' })
    expect(resolutionStateBadge('resolved')).toMatchObject({ label: '客户确认已解决' })
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
  it.each(['planned', 'pending', 'queued', 'running', 'processing', 'dispatching', 'reconciling', 'manual_review'])(
    'shows %s as waiting or in progress regardless of the legacy completion boolean', status => {
      const members = teamMembers([false, true].map(ok => ({ role: 'fix', status, ok })))
      expect(members.map(m => m.status)).toEqual([runStatusBadge(status), runStatusBadge(status)])
      expect(members.every(m => !['danger', 'success'].includes(m.ok.tone))).toBe(true)
    },
  )
  it('keeps explicit failures ahead of completed booleans and does not invent missing results', () => {
    const failed = teamMembers([
      { status: 'failed', ok: true }, { status: 'error', ok: true },
      { status: 'completed', ok: true, error: 'failed' }, { status: 'completed', ok: true, handler_failed: true },
      { status: 'completed', ok: true, handler_outputs: { outputs: [{ status: 'handler_failed', ok: true }] } },
      { status: 'completed', ok: true, handler_outputs: { outputs: [null, { status: 'handler_failed', ok: false }] } },
      { status: 'completed', ok: true, handler_outputs: { outputs: [{ status: 'completed', execution_status: 'failed', ok: true }] } },
      { status: 'pending', ok: false, handler_outputs: { outputs: [{ ok: false, error: 'permission_denied' }] } },
    ])
    const uncertain = teamMembers([
      { ok: true }, { status: 'completed' }, { status: 'completed', ok: 'true' },
      { status: 'completed', execution_status: 'pending', ok: true },
      { status: 'completed', ok: true, handler_outputs: { outputs: null } },
      { status: 'completed', ok: true, handler_outputs: { outputs: [null] } },
      { status: 'completed', ok: true, handler_outputs: { outputs: [{ accepted: true, completed: false }] } },
      { status: 'completed', ok: true, handler_outputs: { outputs: [{ status: 'pending', ok: true }] } },
      { status: 'completed', ok: true, handler_outputs: { outputs: [{ status: 'completed', execution_status: 'pending', ok: true }] } },
      { status: 'completed', ok: true, handler_outputs: { outputs: [{ status: 'unknown', ok: true }] } },
      { status: 'completed', ok: true, handler_outputs: { outputs: [{ ok: true, outcome: 'unknown' }] } },
      { status: 'completed', ok: true, handler_outputs: { outputs: [{ ok: true, partial: true }] } },
      { status: 'completed', ok: true, handler_outputs: { outputs: [{ handler: 'para_delegate', ok: true, accepted: true, completed: true }] } },
      { status: 'completed', ok: true, handler_outputs: { outputs: [{ ok: false, error: 'timeout', requires_reconciliation: true }] } },
    ])
    const completed = teamMembers([
      { status: 'completed', ok: true },
      { status: 'completed', ok: true, handler_outputs: { outputs: [{ status: 'para_task_completed', ok: true, completed: true }] } },
      { status: 'completed', ok: true, handler_outputs: { outputs: [{ handler: 'para_delegate', status: 'para_task_completed', ok: true, accepted: true, completed: true, task_id: 'task-1' }] } },
    ])
    expect(failed.every(m => m.status.tone === 'danger' && m.ok.tone === 'danger')).toBe(true)
    expect(uncertain.every(m => m.status.tone === 'warning' && m.ok.tone === 'warning')).toBe(true)
    expect(completed.every(m => m.ok.label === '成功' && m.ok.tone === 'success')).toBe(true)
    const waiting = teamMembers([true, false].map(requires_reconciliation => ({ status: 'pending', ok: false,
      handler_outputs: { outputs: [{ ok: false, error: 'timeout', accepted: true, requires_reconciliation }] } })))
    expect(waiting.every(m => m.status.tone === 'neutral' && m.ok.tone === 'neutral')).toBe(true)
  })
  it('renders the original ticket 45 waiting shape without changing its raw action or historical reports', () => {
    // Same state/receipt shape as ticket45-projection-baseline.json action62/event85793;
    // identifiers and progress text are synthetic, with no customer content copied into source.
    const roles = [
      { role: 'scout', status: 'pending', ok: false, attempt_id: 'attempt-1', handler_outputs: { outputs: [
        { handler: 'para_delegate', status: 'para_task_accepted', ok: true, accepted: true, completed: false, task_id: 'task-1' },
      ] } },
      { role: 'fix', status: 'planned', ok: false, attempt_id: null, handler_outputs: { outputs: [] } },
      { role: 'verify', status: 'planned', ok: false, attempt_id: null, handler_outputs: { outputs: [] } },
    ]
    const action = { id: 62, action_type: 'employee.dispatch', status: 'pending', error: '',
      recorded_status: 'failed', recorded_error: '未成功角色：fix、verify', request: { team_ok: false, roles }, result: { roles } }
    const evidence = { employee_reports: [{ team_ok: false, progress: '待执行' }, { team_ok: true }, {},
      { status: 'error', team_ok: true }, { status: 'completed', execution_status: 'failed', team_ok: true }] }
    const before = JSON.stringify({ action, evidence })
    const items = buildTimeline([], [action], evidence)
    expect(items[0].badges).toEqual([runStatusBadge('pending')])
    expect(items[0].team.map(m => m.ok.label)).toEqual(['待执行', '待执行', '待执行'])
    expect(items.slice(1).map(i => i.badges[0])).toMatchObject([
      { label: '历史回写：未确认完成', tone: 'neutral' }, { label: '历史回写：标记完成', tone: 'neutral' },
      { label: '历史回写：结果未记录', tone: 'neutral' }, { label: '历史回写：失败', tone: 'danger' },
      { label: '历史回写：失败', tone: 'danger' },
    ])
    expect(items[0].raw).toBe(action)
    expect(items[1].raw).toBe(evidence.employee_reports[0])
    expect(JSON.stringify({ action, evidence })).toBe(before)
  })
  it('does not show a completed group as successful when role state or required result fields disagree', () => {
    const completed = { role: 'fix', status: 'completed', ok: true }
    const roles = ['scout', 'fix', 'verify'].map(role => ({ ...completed, role }))
    const requests = [
      { team_ok: true, roles },
      { team_ok: true, roles: [roles[0], { ...completed, status: 'error' }, roles[2]] },
      { team_ok: true, roles: [roles[0], { ...completed, status: 'planned' }, roles[2]] },
      { team_ok: true }, { roles: [completed] },
      { team_ok: true, roles: [completed, null] }, { team_ok: 'true', roles: [completed] },
      { team_ok: true, roles: [completed] }, { team_ok: true, roles: [roles[0], completed, completed] },
    ]
    const items = buildTimeline([], requests.map((request, id) => ({ id, action_type: 'employee.dispatch', status: 'completed', request })), {})
    expect(items[0].badges[0]).toMatchObject({ label: '小组处理成功', tone: 'success' })
    expect(items[1].badges[0]).toMatchObject({ label: '小组处理未成功', tone: 'danger' })
    expect(items[2].badges[0]).toMatchObject({ label: '待执行', tone: 'neutral' })
    expect(items.slice(3).every(i => i.badges.every(b => b.tone === 'warning'))).toBe(true)
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

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const wfEnabled = vi.hoisted(() => ({
  enabled: { label_print: false, receipt_confirm: false, wechat_msg: false } as Record<string, boolean>,
}))

vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: () => ({
    enabled: wfEnabled.enabled,
    $subscribe: vi.fn(),
  }),
}))
vi.mock('@/utils/tenantStorageScope', () => ({
  buildTenantScopedStorageKey: (k: string, s: string) => `${k}:${s}`,
  resolveTenantStorageScopeFromRuntime: () => 't1',
}))
vi.mock('@/utils/workflowEmployeeDisplayName', () => ({
  shortNameFromPanelTitle: (t: string) => String(t || '').slice(0, 6),
}))

import { useWorkflowEmployeeSpaceStore } from './workflowEmployeeSpace'

describe('workflowEmployeeSpace store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
    wfEnabled.enabled = { label_print: false, receipt_confirm: false, wechat_msg: false }
    vi.useFakeTimers()
  })

  it('applyFromWorkflowPayload creates snapshot and bumps processed', () => {
    const s = useWorkflowEmployeeSpaceStore()
    s.applyFromWorkflowPayload('工作流 · 测试', {
      employeeId: 'emp1',
      workflowStageLine: '阶段A',
      workflowProgressPct: 50,
      workflowProgressLabel: '进行中',
      workflowCurrentHint: '提示',
      workflowProgressIdle: false,
      workflowProgressStarted: true,
    })
    expect(s.snapshots.emp1.stage).toBe('阶段A')
    expect(s.snapshots.emp1.visuallyBusy).toBe(true)
    expect(s.sessions.emp1.processedCount).toBe(1)
  })

  it('applyFromWorkflowPayload ignores empty empId', () => {
    const s = useWorkflowEmployeeSpaceStore()
    s.applyFromWorkflowPayload('t', { employeeId: '' })
    expect(Object.keys(s.snapshots)).toHaveLength(0)
  })

  it('same snapshot does not bump processed again', () => {
    const s = useWorkflowEmployeeSpaceStore()
    const payload = {
      employeeId: 'emp2',
      workflowStageLine: 'A',
      workflowProgressPct: 10,
      workflowProgressLabel: 'x',
      workflowCurrentHint: 'h',
      workflowProgressIdle: false,
      workflowProgressStarted: false,
    }
    s.applyFromWorkflowPayload('工作流 · 二', payload)
    s.applyFromWorkflowPayload('工作流 · 二', payload)
    expect(s.sessions.emp2.processedCount).toBe(1)
  })

  it('heartbeat does not bump processed', () => {
    const s = useWorkflowEmployeeSpaceStore()
    s.applyFromWorkflowPayload('t', { employeeId: 'emp3', workflowProgressPct: 5 }, { isHeartbeat: true })
    expect(s.sessions.emp3?.processedCount ?? 0).toBe(0)
  })

  it('markEnabled then markDisabled accumulates lifetime', () => {
    const s = useWorkflowEmployeeSpaceStore()
    s.markEnabled('emp4')
    expect(s.sessions.emp4.enabledAt).not.toBeNull()
    s.markEnabled('emp4')
    vi.advanceTimersByTime(1000)
    s.markDisabled('emp4')
    expect(s.sessions.emp4.enabledAt).toBeNull()
    expect(s.sessions.emp4.lifetimeMs).toBeGreaterThanOrEqual(1000)
  })

  it('markEnabled/markDisabled ignore empty and missing', () => {
    const s = useWorkflowEmployeeSpaceStore()
    s.markEnabled('')
    s.markDisabled('')
    s.markDisabled('never')
    expect(Object.keys(s.sessions)).toHaveLength(0)
  })

  it('label print bridge gated by enabled flag', () => {
    const s = useWorkflowEmployeeSpaceStore()
    s.applyLabelPrintBridge({ line: 'hi' })
    expect(s.snapshots.label_print).toBeUndefined()
    wfEnabled.enabled.label_print = true
    s.applyLabelPrintBridge({ line: 'hi' })
    expect(s.snapshots.label_print).toBeDefined()
  })

  it('receipt and wechat bridges write snapshots when enabled', () => {
    wfEnabled.enabled.receipt_confirm = true
    wfEnabled.enabled.wechat_msg = true
    const s = useWorkflowEmployeeSpaceStore()
    s.applyReceiptBridge({ contactName: '张三', intentLabel: '收货', messageText: '到了' })
    expect(s.snapshots.receipt_confirm).toBeDefined()
    s.applyWechatMsgBridge({ contactName: '李四', messageText: '你好' })
    expect(s.snapshots.wechat_msg).toBeDefined()
    s.applyWechatStarFeedPolledBridge({ contactCount: 3, intervalMs: 30000, ok: true })
    expect(s.snapshots.wechat_msg.hintLine).toContain('轮询')
  })

  it('removeEmployee deletes snapshot', () => {
    const s = useWorkflowEmployeeSpaceStore()
    s.applyFromWorkflowPayload('t', { employeeId: 'emp5', workflowProgressPct: 1 })
    expect(s.snapshots.emp5).toBeDefined()
    s.removeEmployee('emp5')
    expect(s.snapshots.emp5).toBeUndefined()
    s.removeEmployee('nope')
  })

  it('hydrate from storage parses persisted snapshots and sessions', () => {
    sessionStorage.setItem(
      'xcagi_workflow_employee_space_v1:t1',
      JSON.stringify({ schemaVersion: 1, snapshots: { e: { empId: 'e', stage: 'X' } } }),
    )
    localStorage.setItem(
      'xcagi_workflow_employee_sessions_v1:t1',
      JSON.stringify({ schemaVersion: 1, sessions: { e: { empId: 'e', processedCount: 2 } } }),
    )
    const s = useWorkflowEmployeeSpaceStore()
    s.hydrateFromSessionStorage('t1')
    s.hydrateSessionsFromLocalStorage('t1')
    expect(s.snapshots.e.stage).toBe('X')
    expect(s.sessions.e.processedCount).toBe(2)
  })

  it('hydrate handles malformed and wrong schema gracefully', () => {
    sessionStorage.setItem('xcagi_workflow_employee_space_v1:t1', '{bad')
    localStorage.setItem('xcagi_workflow_employee_sessions_v1:t1', JSON.stringify({ schemaVersion: 2 }))
    const s = useWorkflowEmployeeSpaceStore()
    s.hydrateFromSessionStorage('t1')
    s.hydrateSessionsFromLocalStorage('t1')
    expect(s.snapshots).toEqual({})
    expect(s.sessions).toEqual({})
  })
})

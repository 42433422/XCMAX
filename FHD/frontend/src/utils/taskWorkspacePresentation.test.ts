import { describe, expect, it } from 'vitest'
import type { AgentTaskSummary } from '@/api/agentRuns'
import { taskNeedsApproval, taskProgressPercent, taskStatusLabel, taskUnreadCount } from './taskWorkspacePresentation'

function task(overrides: Partial<AgentTaskSummary> = {}): AgentTaskSummary {
  return {
    task_id: 'task-1',
    user_id: 'owner',
    title: '统一工作区',
    source: 'agent',
    task_type: 'agent',
    status: 'completed',
    attempt: 1,
    run_count: 1,
    ...overrides,
  }
}

describe('taskWorkspacePresentation', () => {
  it('normalizes progress, unread and approval signals for every workspace surface', () => {
    expect(taskProgressPercent(task({ progress: { percent: 145 } as never }))).toBe(100)
    expect(taskUnreadCount(task({ attention_state: 'result_unread' }))).toBe(1)
    expect(taskNeedsApproval(task({ status: 'waiting_user' }))).toBe(true)
    expect(taskStatusLabel('paused')).toBe('已暂停')
  })

  it('fails closed and applies deterministic fallbacks for sparse task snapshots', () => {
    expect(taskUnreadCount(null)).toBe(0)
    expect(taskUnreadCount(task({ unread_count: -3 }))).toBe(0)
    expect(taskUnreadCount(task({ unread_count: 4 }))).toBe(4)
    expect(taskUnreadCount(task({ unread_count: Number.NaN }))).toBe(0)

    expect(taskNeedsApproval(undefined)).toBe(false)
    expect(taskNeedsApproval(task({ approval_required: true }))).toBe(true)
    expect(taskNeedsApproval(task({ attention_state: 'approval_required' }))).toBe(true)
    expect(taskNeedsApproval(task({ status: 'running' }))).toBe(false)

    expect(taskProgressPercent(undefined)).toBe(0)
    expect(taskProgressPercent(task({ progress: { percent: -12 } as never }))).toBe(0)
    expect(taskProgressPercent(task({ progress: { percent: Number.NaN } as never }))).toBe(100)
    expect(taskProgressPercent(task({ status: 'running', progress: undefined }))).toBe(0)
    expect(taskStatusLabel('custom_state')).toBe('custom_state')
    expect(taskStatusLabel(undefined)).toBe('未知')
  })
})

import { describe, expect, it } from 'vitest'
import type { AgentTaskSummary } from '@/api/agentRuns'
import {
  taskNeedsApproval,
  taskProgressPercent,
  taskStatusLabel,
  taskUnreadCount,
} from './taskWorkspacePresentation'

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
})

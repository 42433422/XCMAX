import { describe, expect, it } from 'vitest'

import type { TaskItem } from '@/composables/useChatPersistence'
import {
  agentRunEvidenceSummary,
  hasWorkflowBody,
  workflowPayload,
} from './chatTaskEvidence'

function task(payload?: Record<string, unknown>): TaskItem {
  return {
    id: 'task-1',
    type: 'agent_run',
    title: 'Agent run',
    source: 'agent',
    status: 'running',
    startedAt: 1,
    updatedAt: 1,
    payload,
  }
}

describe('chatTaskEvidence', () => {
  it('detects persisted workflow progress', () => {
    expect(workflowPayload(task())).toEqual({})
    expect(hasWorkflowBody(task())).toBe(false)
    expect(hasWorkflowBody(task({ workflowProgressPct: 0 }))).toBe(true)
    expect(hasWorkflowBody(task({ workflowMonitorLine: '正在校验' }))).toBe(true)
    expect(hasWorkflowBody(task({ workflowCurrentHint: '等待审批' }))).toBe(true)
    expect(
      hasWorkflowBody(
        task({ workflowSteps: [{ id: 'step-1', label: '读取工作簿', status: 'running' }] }),
      ),
    ).toBe(true)
  })

  it('summarizes governed run evidence without duplicating databases', () => {
    const evidenceTask = task({
      orchestrationTrace: [
        {
          id: 'trace-1',
          eventId: 'event-1',
          eventType: 'tool.completed',
          status: 'success',
          evidence: {
            kind: 'print',
            databases: [
              { runtime_database: 'products.db' },
              { runtime_database: 'products.db' },
              { database_id: 'customers' },
            ],
            employees: [{ employee_id: 'employee-1' }],
            changes: [
              { counts: { created: 2, updated: 1 } },
              { counts: { deleted: 3 } },
            ],
          },
        },
      ],
    })

    expect(agentRunEvidenceSummary(evidenceTask)).toBe(
      '读取 products.db、customers · AI 员工 1 · 打单 1 · 新增 2 · 修改 1 · 删除 3',
    )
    expect(agentRunEvidenceSummary(task())).toBe('')
  })
})

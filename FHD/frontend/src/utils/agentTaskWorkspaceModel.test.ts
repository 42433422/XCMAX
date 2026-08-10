import { describe, expect, it } from 'vitest'
import type { AgentRun } from '@/api/agentRuns'
import {
  activeRunIdOfTask,
  conversationIdOfTask,
  groupAgentRunsIntoTasks,
} from './agentTaskWorkspaceModel'

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    run_id: 'run-1',
    user_id: '7',
    message: '核对销售数据',
    status: 'completed',
    created_at: '2026-08-10T08:00:00Z',
    updated_at: '2026-08-10T08:01:00Z',
    metadata: {
      task_context: {
        task_id: 'conversation-sales',
        title: '销售核对',
        conversation_id: 'conversation-sales',
        root_run_id: 'run-1',
        attempt: 1,
        workspace_id: 'sales',
        isolation: 'business_workspace',
      },
    },
    steps: [],
    tool_calls: [],
    events: [],
    artifacts: [],
    ...overrides,
  }
}

describe('groupAgentRunsIntoTasks', () => {
  it('groups multiple runs in one conversation into one durable task', () => {
    const first = run()
    const second = run({
      run_id: 'run-2',
      message: '继续生成报告',
      status: 'waiting_user',
      created_at: '2026-08-10T08:02:00Z',
      updated_at: '2026-08-10T08:03:00Z',
      steps: [
        { step_id: 'step-1', node_id: 'query', tool_id: 'sales', action: 'query', status: 'completed' },
        { step_id: 'step-2', node_id: 'write', tool_id: 'report', action: 'create', status: 'waiting_user' },
      ],
      tool_calls: [
        { call_id: 'call-1', tool_id: 'sales', action: 'query', status: 'completed' },
      ],
      metadata: {
        task_context: {
          task_id: 'conversation-sales',
          title: '继续生成报告',
          conversation_id: 'conversation-sales',
          root_run_id: 'run-2',
          attempt: 1,
          workspace_id: 'sales',
          isolation: 'business_workspace',
        },
      },
    })

    const tasks = groupAgentRunsIntoTasks([first, second])

    expect(tasks).toHaveLength(1)
    expect(tasks[0].id).toBe('agent_task_conversation-sales')
    expect(tasks[0].title).toBe('销售核对')
    expect(tasks[0].status).toBe('blocked')
    expect(tasks[0].progress).toBe(50)
    expect(tasks[0].payload?.runCount).toBe(2)
    expect(activeRunIdOfTask(tasks[0])).toBe('run-2')
    expect(conversationIdOfTask(tasks[0])).toBe('conversation-sales')
  })

  it('keeps different conversations isolated', () => {
    const tasks = groupAgentRunsIntoTasks([
      run(),
      run({
        run_id: 'run-other',
        metadata: {
          task_context: {
            task_id: 'conversation-stock',
            title: '库存任务',
            conversation_id: 'conversation-stock',
          },
        },
      }),
    ])

    expect(tasks.map((task) => task.id).sort()).toEqual([
      'agent_task_conversation-sales',
      'agent_task_conversation-stock',
    ])
  })

  it('does not invent a percentage when a task has no explicit steps', () => {
    const [task] = groupAgentRunsIntoTasks([run()])

    expect(task.status).toBe('success')
    expect(task.progress).toBeUndefined()
  })
})

import { describe, expect, it } from 'vitest'
import type { AgentRun } from '@/api/agentRuns'
import {
  activeRunIdOfTask,
  conversationIdOfTask,
  groupAgentRunsIntoTasks,
  taskSummariesToTaskItems,
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

  it('maps every runtime lifecycle state to a stable task state and stage', () => {
    const cases = [
      ['queued', 'queued', '排队中'],
      ['planning', 'running', '正在生成执行计划'],
      ['running', 'running', '执行中'],
      ['retrying', 'running', '正在重试'],
      ['waiting_user', 'blocked', '等待审批或用户确认'],
      ['blocked', 'blocked', '等待依赖解除'],
      ['paused', 'paused', '已暂停，可继续'],
      ['completed', 'success', '任务完成'],
      ['failed', 'failed', '执行失败'],
      ['cancelled', 'cancelled', '已中断'],
      ['future_state', 'queued', '状态待同步'],
    ] as const
    const runs = cases.map(([status], index) => run({
      run_id: `run-${status}`,
      status,
      metadata: {
        task_context: {
          task_id: `task-${index}`,
          title: status,
          conversation_id: `conversation-${index}`,
        },
      },
    }))

    const tasks = groupAgentRunsIntoTasks(runs)

    cases.forEach(([rawStatus, expectedStatus, expectedStage], index) => {
      const task = tasks.find((candidate) => candidate.id === `agent_task_task-${index}`)
      expect(task?.title).toBe(rawStatus)
      expect(task?.status).toBe(expectedStatus)
      expect(task?.stage).toBe(expectedStage)
    })
  })

  it('uses safe runtime fallbacks, keeps evidence, and ignores invalid run identities', () => {
    const taskless = run({
      run_id: 'run-runtime-only',
      message: '运行时兜底任务',
      status: 'failed',
      error: '',
      created_at: 'invalid-date',
      updated_at: 'invalid-date',
      artifacts: [{ artifact_id: 'artifact-1', name: 'test-report' }],
      metadata: {
        runtime_context: {
          session_id: 'session-runtime',
          workspace: 'workspace-runtime',
          worktree_path: '/tmp/runtime-worktree',
        },
        delivery_evidence: { kind: 'test', passed: true },
      },
    })
    const ignored = run({ run_id: '   ' })

    const [task] = groupAgentRunsIntoTasks([ignored, taskless])

    expect(task.id).toBe('agent_task_session-runtime')
    expect(task.title).toBe('运行时兜底任务')
    expect(task.status).toBe('failed')
    expect(task.error).toBe('任务执行失败')
    expect(task.startedAt).toBeGreaterThan(0)
    expect(task.updatedAt).toBeGreaterThan(0)
    expect(task.payload?.conversationId).toBe('session-runtime')
    expect(task.payload?.workspaceId).toBe('workspace-runtime')
    expect(task.payload?.workspacePath).toBe('/tmp/runtime-worktree')
    expect(task.payload?.workspaceIsolation).toBe('business_workspace')
    expect(task.payload?.artifactCount).toBe(1)
    expect(task.payload?.deliveryEvidence).toEqual([{ kind: 'test', passed: true }])
  })

  it('keeps array delivery evidence and settles completed, failed, and skipped steps', () => {
    const [task] = groupAgentRunsIntoTasks([run({
      metadata: {
        task_context: {
          task_id: '',
          title: '',
          conversation_id: '',
          attempt: 0,
        },
        delivery: [{ kind: 'commit' }, { kind: 'test' }],
      },
      steps: [
        { step_id: 'done', node_id: 'one', tool_id: 'git', action: 'commit', status: 'completed' },
        { step_id: 'failed', node_id: 'two', tool_id: 'test', action: 'run', status: 'failed' },
        { step_id: 'skipped', node_id: 'three', tool_id: 'pr', action: 'open', status: 'skipped' },
        { step_id: 'running', node_id: 'four', tool_id: 'ci', action: 'wait', status: 'running' },
      ],
    })])

    expect(task.id).toBe('agent_task_run-1')
    expect(task.title).toBe('核对销售数据')
    expect(task.progress).toBe(75)
    expect(task.payload?.attempt).toBe(1)
    expect(task.payload?.deliveryEvidence).toEqual([{ kind: 'commit' }, { kind: 'test' }])
  })

  it('shows a durable cooperative control request until the worker applies it', () => {
    const active = run({ status: 'running' })
    const [task] = taskSummariesToTaskItems([{
      task_id: 'conversation-sales',
      user_id: '7',
      title: '销售核对',
      source: 'agent',
      task_type: 'agent',
      status: 'running',
      attempt: 1,
      run_count: 1,
      active_run_id: active.run_id,
      runs: [active],
      active_run: active,
      control_command: {
        command_id: 'taskcmd-1',
        task_id: 'conversation-sales',
        run_id: active.run_id,
        action: 'pause',
        status: 'requested',
      },
    }])

    expect(task.status).toBe('running')
    expect(task.stage).toBe('正在请求暂停')
    expect(task.payload?.controlCommand).toMatchObject({
      command_id: 'taskcmd-1',
      status: 'requested',
    })
  })
})

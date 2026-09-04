import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { AgentRun } from '@/api/agentRuns'
import type { TaskItem } from './useChatPersistence'
import { bindPendingFirstAiTaskRun, isFirstAiTaskPending, queueFirstAiTaskPrompt, readProductFlowCompleted } from '@/constants/productFlow'

const apiMock = vi.hoisted(() => ({
  listTasks: vi.fn(),
  listRuns: vi.fn(),
  archiveTask: vi.fn(),
  pauseRun: vi.fn(),
  resumeRun: vi.fn(),
  cancelRun: vi.fn(),
  retryRun: vi.fn(),
  getRun: vi.fn(),
  continueRun: vi.fn(),
  markTaskRead: vi.fn(),
  taskEventStreamPath: vi.fn(),
}))

vi.mock('@/api/agentRuns', () => ({ default: apiMock }))

import { useAgentTaskWorkspace } from './useAgentTaskWorkspace'

function serverRun(status = 'running'): AgentRun {
  return {
    run_id: 'run-1',
    user_id: '7',
    message: '生成月报',
    status,
    created_at: '2026-08-10T08:00:00Z',
    updated_at: '2026-08-10T08:01:00Z',
    metadata: {
      task_context: {
        task_id: 'conversation-monthly',
        title: '生成月报',
        conversation_id: 'conversation-monthly',
      },
    },
    steps: [],
    events: [],
  }
}

function serverTask(status = 'running') {
  const run = serverRun(status)
  return {
    task_id: 'conversation-monthly',
    user_id: '7',
    title: '生成月报',
    source: 'agent',
    task_type: 'agent',
    status,
    attempt: 1,
    run_count: 1,
    active_run_id: run.run_id,
    created_at: run.created_at,
    updated_at: run.updated_at,
    runs: [run],
    active_run: run,
  }
}

describe('useAgentTaskWorkspace', () => {
  const originalEventSource = globalThis.EventSource

  beforeEach(() => {
    localStorage.clear()
    Object.values(apiMock).forEach((mock) => mock.mockReset().mockResolvedValue({ success: true }))
    apiMock.listTasks.mockResolvedValue({ success: true, data: [serverTask()] })
    apiMock.listRuns.mockResolvedValue({ success: true, data: [serverRun()] })
    apiMock.getRun.mockResolvedValue({
      success: true,
      data: serverRun('waiting_user'),
      approval: { grant: 'bound-grant' },
    })
    apiMock.taskEventStreamPath.mockReturnValue('/api/agent/tasks/events/stream')
  })

  afterEach(() => {
    globalThis.EventSource = originalEventSource
    vi.useRealTimers()
  })

  function setup() {
    const taskList = ref<TaskItem[]>([])
    const activeTaskId = ref('')
    const expandedTaskIds = ref<string[]>([])
    const sortTaskList = vi.fn()
    const onOpenConversation = vi.fn().mockImplementation(async () => {
      expandedTaskIds.value = []
    })
    const workspace = useAgentTaskWorkspace({
      taskList,
      activeTaskId,
      expandedTaskIds,
      sortTaskList,
      onOpenConversation,
    })
    return { taskList, activeTaskId, expandedTaskIds, sortTaskList, onOpenConversation, workspace }
  }

  it('hydrates a server-backed task and restores its conversation', async () => {
    const state = setup()

    await state.workspace.refreshTasks()
    const task = state.taskList.value[0]
    await state.workspace.selectTask(task)

    expect(task.id).toBe('agent_task_conversation-monthly')
    expect(state.activeTaskId.value).toBe(task.id)
    expect(state.expandedTaskIds.value).toContain(task.id)
    expect(state.onOpenConversation).toHaveBeenCalledWith('conversation-monthly')
    expect(apiMock.markTaskRead).toHaveBeenCalledWith('conversation-monthly')
  })

  it('controls the exact active run and refreshes the durable snapshot', async () => {
    const state = setup()
    await state.workspace.refreshTasks()

    await state.workspace.controlTask('agent_task_conversation-monthly', 'pause')
    await state.workspace.controlTask('agent_task_conversation-monthly', 'cancel')

    expect(apiMock.pauseRun).toHaveBeenCalledWith('run-1')
    expect(apiMock.cancelRun).toHaveBeenCalledWith('run-1')
    expect(apiMock.listTasks).toHaveBeenCalledTimes(3)
  })

  it('archives completed tasks in the server SSOT without deleting a run', async () => {
    apiMock.listTasks
      .mockResolvedValueOnce({ success: true, data: [serverTask('completed')] })
      .mockResolvedValue({ success: true, data: [] })
    const state = setup()
    await state.workspace.refreshTasks()

    await state.workspace.archiveCompletedTasks()
    await state.workspace.refreshTasks()

    expect(state.taskList.value).toHaveLength(0)
    expect(apiMock.archiveTask).toHaveBeenCalledWith('conversation-monthly')
    expect(apiMock.cancelRun).not.toHaveBeenCalled()
  })

  it('approves through a fresh action-bound grant and refreshes evidence', async () => {
    apiMock.listTasks.mockResolvedValue({ success: true, data: [serverTask('waiting_user')] })
    const state = setup()
    await state.workspace.refreshTasks()

    await state.workspace.controlTask('agent_task_conversation-monthly', 'approve')

    expect(apiMock.getRun).toHaveBeenCalledWith('run-1')
    expect(apiMock.continueRun).toHaveBeenCalledWith('run-1', {
      approval_grant: 'bound-grant',
    })
    expect(apiMock.listTasks).toHaveBeenCalledTimes(2)
  })

  it('uses the refreshed durable task snapshot to close the bound first-order onboarding', async () => {
    queueFirstAiTaskPrompt('这是我的新手第一单，请创建演示出货单')
    bindPendingFirstAiTaskRun('run-1', '这是我的新手第一单，请创建演示出货单')
    const completedRun = serverRun('completed')
    completedRun.intent = 'onboarding_first_order'
    completedRun.steps = [
      {
        step_id: 's1',
        node_id: 'n1',
        tool_id: 'business_db',
        action: 'read',
        status: 'completed',
        params: { entity: 'customers' },
        output: { success: true },
      },
      {
        step_id: 's2',
        node_id: 'n2',
        tool_id: 'business_db',
        action: 'read',
        status: 'completed',
        params: { entity: 'products' },
        output: { success: true },
      },
      {
        step_id: 's3',
        node_id: 'n3',
        tool_id: 'business_db',
        action: 'write',
        status: 'completed',
        params: { entity: 'shipment_records' },
        output: { success: true },
      },
    ]
    const task = serverTask('completed')
    task.runs = [completedRun]
    task.active_run = completedRun
    apiMock.listTasks.mockResolvedValue({ success: true, data: [task] })

    await setup().workspace.refreshTasks()

    expect(readProductFlowCompleted()).toBe(true)
    expect(isFirstAiTaskPending()).toBe(false)
  })

  it('uses task snapshots as the live clock and keeps polling as a slow fallback', async () => {
    class FakeEventSource {
      static instances: FakeEventSource[] = []
      readonly listeners = new Map<string, (event: MessageEvent) => void>()
      onerror: (() => void) | null = null
      closed = false

      constructor(readonly url: string) {
        FakeEventSource.instances.push(this)
      }

      addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
        this.listeners.set(type, listener as (event: MessageEvent) => void)
      }

      emit(type: string, payload: unknown): void {
        this.listeners.get(type)?.({ data: JSON.stringify(payload) } as MessageEvent)
      }

      close(): void {
        this.closed = true
      }
    }

    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource
    vi.useFakeTimers()
    const state = setup()
    state.workspace.start()
    await Promise.resolve()

    expect(FakeEventSource.instances[0]?.url).toContain('/api/agent/tasks/events/stream')
    FakeEventSource.instances[0]?.emit('task.snapshot', [serverTask('completed')])
    expect(state.taskList.value[0]?.status).toBe('success')

    await vi.advanceTimersByTimeAsync(14_999)
    expect(apiMock.listTasks).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(apiMock.listTasks).toHaveBeenCalledTimes(2)

    state.workspace.stop()
    expect(FakeEventSource.instances[0]?.closed).toBe(true)
  })
})

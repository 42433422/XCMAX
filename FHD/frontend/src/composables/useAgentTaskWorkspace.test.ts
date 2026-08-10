import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { AgentRun } from '@/api/agentRuns'
import type { TaskItem } from './useChatPersistence'

const apiMock = vi.hoisted(() => ({
  listRuns: vi.fn(),
  pauseRun: vi.fn(),
  resumeRun: vi.fn(),
  cancelRun: vi.fn(),
  retryRun: vi.fn(),
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

describe('useAgentTaskWorkspace', () => {
  beforeEach(() => {
    localStorage.clear()
    Object.values(apiMock).forEach((mock) => mock.mockReset().mockResolvedValue({ success: true }))
    apiMock.listRuns.mockResolvedValue({ success: true, data: [serverRun()] })
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
  })

  it('controls the exact active run and refreshes the durable snapshot', async () => {
    const state = setup()
    await state.workspace.refreshTasks()

    await state.workspace.controlTask('agent_task_conversation-monthly', 'pause')
    await state.workspace.controlTask('agent_task_conversation-monthly', 'cancel')

    expect(apiMock.pauseRun).toHaveBeenCalledWith('run-1')
    expect(apiMock.cancelRun).toHaveBeenCalledWith('run-1')
    expect(apiMock.listRuns).toHaveBeenCalledTimes(3)
  })

  it('archives completed tasks locally without deleting the server run', async () => {
    apiMock.listRuns.mockResolvedValue({ success: true, data: [serverRun('completed')] })
    const state = setup()
    await state.workspace.refreshTasks()

    state.workspace.archiveCompletedTasks()
    await state.workspace.refreshTasks()

    expect(state.taskList.value).toHaveLength(0)
    expect(apiMock.cancelRun).not.toHaveBeenCalled()
  })
})

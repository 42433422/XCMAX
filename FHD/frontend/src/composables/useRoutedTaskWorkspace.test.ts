import { effectScope, nextTick, reactive, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { resolveWorkspaceSessionId, useRoutedTaskWorkspace } from './useRoutedTaskWorkspace'

const apiMock = vi.hoisted(() => ({ markTaskRead: vi.fn() }))
vi.mock('@/api/agentRuns', () => ({ default: apiMock }))

const firstTask = {
  id: 'local-1',
  type: 'agent',
  title: '客户B销售开票',
  source: 'agent' as const,
  status: 'blocked' as const,
  progress: 45,
  stage: '等待审批',
  startedAt: 1,
  updatedAt: 2,
  payload: { taskId: 'task-approval' },
}
const secondTask = {
  ...firstTask,
  id: 'local-2',
  title: '月度经营报告',
  status: 'success' as const,
  progress: 100,
  stage: '任务完成',
  payload: { taskId: 'task-result' },
}

describe('useRoutedTaskWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.markTaskRead.mockResolvedValue({ success: true })
  })

  it('isolates the selected task, switches its conversation and durably marks it read', async () => {
    const props = reactive({
      workspaceTaskId: 'task-approval',
      workspaceConversationId: 'chat-approval',
    })
    const currentSessionId = ref('chat-approval')
    const taskList = ref([firstTask, secondTask])
    const filteredTaskList = ref([firstTask, secondTask])
    const activeTaskId = ref('local-2')
    const loadSession = vi.fn(async (conversationId: string) => {
      currentSessionId.value = conversationId
    })
    const markTaskRead = vi.fn(async () => undefined)
    const taskSummaries = ref([
      {
        task_id: 'task-approval',
        user_id: 'owner',
        title: '客户B销售开票（服务端）',
        source: 'agent',
        task_type: 'agent',
        status: 'waiting_user',
        attention_state: 'approval_required',
        approval_required: true,
        unread_count: 0,
        attempt: 2,
        run_count: 3,
        progress: {
          percent: 45,
          completed_units: 1,
          settled_units: 1,
          total_units: 2,
          current_unit: 2,
          stage: '等待审批',
          detail: '确认开票',
          status: 'waiting_user',
          attempt: 2,
          indeterminate: false,
          basis: 'steps' as const,
        },
      },
    ])
    const scope = effectScope()
    const workspace = scope.run(() =>
      useRoutedTaskWorkspace({
        props,
        currentSessionId,
        taskList,
        filteredTaskList,
        activeTaskId,
        taskSummaries,
        loadSession,
        markTaskRead,
      }),
    )!
    await nextTick()

    expect(resolveWorkspaceSessionId(props)).toBe('chat-approval')
    expect(workspace.workspaceMode.value).toBe(true)
    expect(workspace.visibleTaskList.value).toEqual([firstTask])
    expect(workspace.visibleFilteredTaskList.value).toEqual([firstTask])
    expect(workspace.visibleActiveTaskId.value).toBe('local-1')
    expect(workspace.activeWorkspaceTask.value?.title).toBe('客户B销售开票')
    expect(markTaskRead).toHaveBeenCalledWith('task-approval')
    expect(workspace.activeWorkspaceSummary.value?.task_id).toBe('task-approval')
    expect(workspace.workspaceHeader.value).toMatchObject({
      title: '客户B销售开票（服务端）',
      status: 'waiting_user',
      stage: '等待审批',
      progress: 45,
      approvalRequired: true,
      attempt: 2,
      runCount: 3,
    })
    expect(loadSession).not.toHaveBeenCalled()

    props.workspaceTaskId = 'task-result'
    props.workspaceConversationId = 'chat-result'
    await nextTick()

    expect(loadSession).toHaveBeenCalledWith('chat-result')
    expect(markTaskRead).toHaveBeenCalledWith('task-result')
    expect(workspace.visibleTaskList.value).toEqual([secondTask])
    expect(workspace.visibleActiveTaskId.value).toBe('local-2')
    scope.stop()
  })

  it('falls back from conversation to task id and leaves the normal chat list unchanged', () => {
    expect(resolveWorkspaceSessionId({ workspaceTaskId: 'task-only' })).toBe('task-only')

    const scope = effectScope()
    const taskList = ref([firstTask, secondTask])
    const workspace = scope.run(() =>
      useRoutedTaskWorkspace({
        props: {},
        currentSessionId: ref('normal-chat'),
        taskList,
        filteredTaskList: ref([secondTask]),
        activeTaskId: ref('local-2'),
        loadSession: vi.fn(),
      }),
    )!

    expect(workspace.workspaceMode.value).toBe(false)
    expect(workspace.visibleTaskList.value).toEqual(taskList.value)
    expect(workspace.visibleFilteredTaskList.value).toEqual([secondTask])
    expect(workspace.visibleActiveTaskId.value).toBe('local-2')
    scope.stop()
  })

  it('builds a safe workspace header when only the routed task id is available', async () => {
    const scope = effectScope()
    const loadSession = vi.fn(async () => undefined)
    const props = reactive<{ workspaceTaskId?: string }>({})
    const workspace = scope.run(() =>
      useRoutedTaskWorkspace({
        props,
        currentSessionId: ref('normal-chat'),
        taskList: ref([]),
        filteredTaskList: ref([]),
        activeTaskId: ref(''),
        taskSummaries: ref([]),
        loadSession,
      }),
    )!
    props.workspaceTaskId = 'server-only-task'
    await nextTick()

    expect(loadSession).toHaveBeenCalledWith('server-only-task')
    expect(apiMock.markTaskRead).toHaveBeenCalledWith('server-only-task')
    expect(workspace.activeWorkspaceTask.value).toBeNull()
    expect(workspace.activeWorkspaceSummary.value).toBeNull()
    expect(workspace.workspaceHeader.value).toEqual({
      title: 'server-only-task',
      status: '',
      stage: '未知',
      progress: undefined,
      unreadCount: 0,
      approvalRequired: false,
      attempt: 1,
      runCount: 1,
      capabilities: {},
    })
    scope.stop()
  })
})

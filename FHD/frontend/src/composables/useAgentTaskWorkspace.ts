import { AuthenticatedEventStream } from '@/utils/authenticatedEventStream'
import { ref, type Ref } from 'vue'
import agentRunsApi from '@/api/agentRuns'
import { approveRunWithFreshGrant } from '@/api/agentRunApproval'
import type { AgentTaskSummary } from '@/api/agentRuns'
import { buildFullApiUrl } from '@/api/core'
import type { TaskItem } from './useChatPersistence'
import { activeRunIdOfTask, conversationIdOfTask, groupAgentRunsIntoTasks, taskSummariesToTaskItems } from '@/utils/agentTaskWorkspaceModel'
import { completeFirstAiTaskFromRun } from '@/constants/productFlow'

export type TaskControlAction = 'pause' | 'resume' | 'cancel' | 'retry' | 'approve'
export type TaskControlState = { pending?: TaskControlAction; error?: string; message?: string; needsVerification?: boolean }
export type TaskSyncState = { checking: boolean; stale: boolean; lastVerifiedAt: number; error: string }

export interface UseAgentTaskWorkspaceOptions {
  taskList: Ref<TaskItem[]>
  activeTaskId: Ref<string>
  expandedTaskIds: Ref<string[]>
  sortTaskList: () => void
  onPersist?: () => void
  onOpenConversation?: (conversationId: string) => Promise<void>
  onJumpToMessage?: (task: TaskItem) => void
}

export function useAgentTaskWorkspace(options: UseAgentTaskWorkspaceOptions) {
  let refreshTimer: number | null = null
  let reconnectTimer: number | null = null
  let taskStream: AuthenticatedEventStream | null = null
  let refreshInFlight: Promise<void> | null = null
  const taskControlStates = ref<Record<string, TaskControlState>>({})
  const taskSyncState = ref<TaskSyncState>({ checking: false, stale: true, lastVerifiedAt: 0, error: '' })
  let lifecycleVersion = 0

  function applyTaskItems(serverTasks: TaskItem[]): void {
    const localTasks = options.taskList.value.filter((task) => !['agent_task', 'agent_run'].includes(task.type))
    options.taskList.value = [...serverTasks, ...localTasks]
    const known = new Set(options.taskList.value.map((task) => task.id))
    options.expandedTaskIds.value = options.expandedTaskIds.value.filter((id) => known.has(id))
    if (!known.has(options.activeTaskId.value)) {
      options.activeTaskId.value = options.taskList.value[0]?.id || ''
    }
    options.sortTaskList()
    options.onPersist?.()
    taskSyncState.value = { checking: false, stale: false, lastVerifiedAt: Date.now(), error: '' }
    for (const state of Object.values(taskControlStates.value)) {
      if (state.needsVerification) {
        state.error = ''
        state.message = '已重新核对任务状态，请查看当前状态后继续操作。'
        state.needsVerification = false
      }
    }
  }

  function applyFirstTaskCompletionEvidence(tasks: AgentTaskSummary[]): void {
    tasks.forEach((task) => {
      const runs = [...(Array.isArray(task.runs) ? task.runs : []), ...(task.active_run ? [task.active_run] : [])]
      runs.forEach((run) => completeFirstAiTaskFromRun(run))
    })
  }

  function applyServerTasks(tasks: AgentTaskSummary[]): void {
    applyFirstTaskCompletionEvidence(tasks)
    applyTaskItems(taskSummariesToTaskItems(tasks))
  }

  async function refreshTasks(afterAction = false): Promise<void> {
    const requestedVersion = lifecycleVersion
    while (refreshInFlight) {
      await refreshInFlight
      if (!afterAction || requestedVersion !== lifecycleVersion) return
    }
    taskSyncState.value.checking = true
    const request = (async () => {
      try {
        let serverTasks: TaskItem[]
        try {
          const response = await agentRunsApi.listTasks({ limit: 200 })
          if (requestedVersion !== lifecycleVersion) return
          if (response?.success === false || !Array.isArray(response?.data)) throw new Error('任务状态读取失败')
          applyFirstTaskCompletionEvidence(response.data)
          serverTasks = taskSummariesToTaskItems(response.data)
        } catch {
          if (requestedVersion !== lifecycleVersion) return
          const response = await agentRunsApi.listRuns({ limit: 200 })
          if (requestedVersion !== lifecycleVersion) return
          if (response?.success === false || !Array.isArray(response?.data)) throw new Error('任务状态读取失败')
          response.data.forEach((run) => completeFirstAiTaskFromRun(run))
          serverTasks = groupAgentRunsIntoTasks(response.data)
        }
        applyTaskItems(serverTasks)
      } catch {
        if (requestedVersion === lifecycleVersion) markStale()
      } finally {
        if (requestedVersion === lifecycleVersion) taskSyncState.value.checking = false
      }
    })()
    refreshInFlight = request
    try { await request } finally { if (refreshInFlight === request) refreshInFlight = null }
  }

  function markStale(): void {
    taskSyncState.value.stale = true
    taskSyncState.value.error = '无法核实当前任务状态，正在显示上次结果；任务可能仍在执行，请勿重复提交。'
  }

  function scheduleReconnect(): void {
    if (reconnectTimer !== null || typeof window === 'undefined') return
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      connectTaskStream()
    }, 1500)
  }

  function connectTaskStream(): void {
    if (typeof window === 'undefined' || typeof fetch === 'undefined') return
    if (typeof agentRunsApi.taskEventStreamPath !== 'function') return
    taskStream?.close()
    const requestedVersion = lifecycleVersion
    const stream = new AuthenticatedEventStream(buildFullApiUrl(agentRunsApi.taskEventStreamPath()))
    taskStream = stream
    const isCurrent = () => requestedVersion === lifecycleVersion && taskStream === stream
    taskStream.addEventListener('task.snapshot', (event) => {
      if (!isCurrent()) return
      try {
        const snapshot = JSON.parse((event as MessageEvent).data)
        if (!Array.isArray(snapshot)) throw new Error('invalid task snapshot')
        applyServerTasks(snapshot as AgentTaskSummary[])
      } catch { markStale() }
    })
    taskStream.addEventListener('stream.closed', () => {
      if (!isCurrent()) return
      markStale()
      taskStream?.close()
      taskStream = null
      scheduleReconnect()
    })
    taskStream.onerror = () => {
      if (!isCurrent()) return
      markStale()
      taskStream?.close()
      taskStream = null
      scheduleReconnect()
    }
  }

  function start(): void {
    void refreshTasks()
    connectTaskStream()
    if (refreshTimer !== null) return
    refreshTimer = window.setInterval(() => void refreshTasks(), 15000)
  }

  function stop(): void {
    lifecycleVersion += 1
    refreshInFlight = null
    taskControlStates.value = {}
    taskSyncState.value = { checking: false, stale: true, lastVerifiedAt: 0, error: '' }
    if (refreshTimer !== null) window.clearInterval(refreshTimer)
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
    taskStream?.close()
    taskStream = null
    refreshTimer = null
    reconnectTimer = null
  }

  async function selectTask(task: TaskItem): Promise<void> {
    const requestedVersion = lifecycleVersion
    options.activeTaskId.value = task.id
    if (!options.expandedTaskIds.value.includes(task.id)) {
      options.expandedTaskIds.value = [...options.expandedTaskIds.value, task.id]
    }
    options.onPersist?.()
    const durableTaskId = String(task.payload?.taskId || '').trim()
    if (durableTaskId) {
      await agentRunsApi.markTaskRead(durableTaskId).catch(() => undefined)
      if (requestedVersion !== lifecycleVersion) return
    }
    const conversationId = conversationIdOfTask(task)
    if (conversationId && options.onOpenConversation) {
      await options.onOpenConversation(conversationId)
      if (requestedVersion !== lifecycleVersion) return
      await refreshTasks()
      if (requestedVersion !== lifecycleVersion) return
      options.activeTaskId.value = task.id
      if (!options.expandedTaskIds.value.includes(task.id)) {
        options.expandedTaskIds.value = [...options.expandedTaskIds.value, task.id]
      }
      options.onPersist?.()
      return
    }
    options.onJumpToMessage?.(task)
  }

  async function controlTask(taskId: string, action: TaskControlAction): Promise<void> {
    if (taskControlStates.value[taskId]?.pending || taskControlStates.value[taskId]?.needsVerification) return
    const requestedVersion = lifecycleVersion
    const task = options.taskList.value.find((item) => item.id === taskId)
    if (!task || task.type !== 'agent_task') return
    const runId = activeRunIdOfTask(task)
    if (!runId) return
    const labels: Record<TaskControlAction, string> = { pause: '暂停', resume: '恢复', cancel: '取消', retry: '重试', approve: '审批' }
    taskControlStates.value[taskId] = { pending: action }
    const state = taskControlStates.value[taskId]
    let accepted = false
    try {
      const result = action === 'approve'
        ? await approveRunWithFreshGrant(runId, { isCurrent: () => requestedVersion === lifecycleVersion })
        : await ({ pause: agentRunsApi.pauseRun, resume: agentRunsApi.resumeRun, cancel: agentRunsApi.cancelRun, retry: agentRunsApi.retryRun })[action](runId)
      if (requestedVersion !== lifecycleVersion) return
      if (result?.success === false) throw new Error('task control rejected')
      accepted = true
      await refreshTasks(true)
      if (requestedVersion !== lifecycleVersion) return
      if (taskSyncState.value.stale) throw new Error('task readback failed')
      state.message = `${labels[action]}请求已提交，已重新核对任务状态。`
    } catch {
      if (requestedVersion !== lifecycleVersion) return
      state.error = `${labels[action]}${accepted ? '请求已提交，但当前结果无法核实' : '未确认成功'}。任务可能仍在执行，请先重新核对状态，勿重复提交。`
      state.needsVerification = true
      markStale()
    } finally {
      if (requestedVersion === lifecycleVersion) {
        delete state.pending
        taskControlStates.value[taskId] = { ...state }
      }
    }
  }

  async function archiveCompletedTasks(): Promise<void> {
    const requestedVersion = lifecycleVersion
    const completed = options.taskList.value.filter(
      (task) => task.type === 'agent_task' && ['success', 'failed', 'cancelled'].includes(task.status),
    )
    await Promise.all(
      completed.map(async (task) => {
        const taskId = String(task.payload?.taskId || '').trim()
        if (taskId) await agentRunsApi.archiveTask(taskId)
      }),
    )
    if (requestedVersion !== lifecycleVersion) return
    const archivedIds = new Set(completed.map((task) => task.id))
    options.taskList.value = options.taskList.value.filter((task) => !archivedIds.has(task.id))
    options.onPersist?.()
  }

  return {
    taskControlStates,
    taskSyncState,
    archiveCompletedTasks,
    controlTask,
    refreshTasks,
    selectTask,
    start,
    stop,
  }
}

import type { Ref } from 'vue'
import agentRunsApi from '@/api/agentRuns'
import type { AgentTaskSummary } from '@/api/agentRuns'
import { buildFullApiUrl } from '@/api/core'
import type { TaskItem } from './useChatPersistence'
import { activeRunIdOfTask, conversationIdOfTask, groupAgentRunsIntoTasks, taskSummariesToTaskItems } from '@/utils/agentTaskWorkspaceModel'

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
  let taskStream: EventSource | null = null
  let refreshInFlight = false

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
  }

  function applyServerTasks(tasks: AgentTaskSummary[]): void {
    applyTaskItems(taskSummariesToTaskItems(tasks))
  }

  async function refreshTasks(): Promise<void> {
    if (refreshInFlight) return
    refreshInFlight = true
    try {
      let serverTasks: TaskItem[]
      try {
        const response = await agentRunsApi.listTasks({ limit: 200 })
        const tasks = Array.isArray(response?.data) ? response.data : []
        serverTasks = taskSummariesToTaskItems(tasks)
      } catch {
        // Compatibility with an older backend during rolling desktop upgrades.
        const response = await agentRunsApi.listRuns({ limit: 200 })
        const runs = Array.isArray(response?.data) ? response.data : []
        serverTasks = groupAgentRunsIntoTasks(runs)
      }
      applyTaskItems(serverTasks)
    } catch {
      // Keep the last durable snapshot in the panel while offline.
    } finally {
      refreshInFlight = false
    }
  }

  function scheduleReconnect(): void {
    if (reconnectTimer !== null || typeof window === 'undefined') return
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      connectTaskStream()
    }, 1500)
  }

  function connectTaskStream(): void {
    if (typeof window === 'undefined' || typeof EventSource === 'undefined') return
    if (typeof agentRunsApi.taskEventStreamPath !== 'function') return
    taskStream?.close()
    taskStream = new EventSource(buildFullApiUrl(agentRunsApi.taskEventStreamPath()), { withCredentials: true })
    taskStream.addEventListener('task.snapshot', (event) => {
      try {
        const snapshot = JSON.parse((event as MessageEvent).data)
        if (Array.isArray(snapshot)) applyServerTasks(snapshot as AgentTaskSummary[])
      } catch {
        // Keep the last durable snapshot; the 15s fallback will retry.
      }
    })
    taskStream.addEventListener('stream.closed', () => {
      taskStream?.close()
      taskStream = null
      scheduleReconnect()
    })
    taskStream.onerror = () => {
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
    if (refreshTimer !== null) window.clearInterval(refreshTimer)
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
    taskStream?.close()
    taskStream = null
    refreshTimer = null
    reconnectTimer = null
  }

  async function selectTask(task: TaskItem): Promise<void> {
    options.activeTaskId.value = task.id
    if (!options.expandedTaskIds.value.includes(task.id)) {
      options.expandedTaskIds.value = [...options.expandedTaskIds.value, task.id]
    }
    options.onPersist?.()
    const durableTaskId = String(task.payload?.taskId || '').trim()
    if (durableTaskId) {
      await agentRunsApi.markTaskRead(durableTaskId).catch(() => undefined)
    }
    const conversationId = conversationIdOfTask(task)
    if (conversationId && options.onOpenConversation) {
      await options.onOpenConversation(conversationId)
      await refreshTasks()
      options.activeTaskId.value = task.id
      if (!options.expandedTaskIds.value.includes(task.id)) {
        options.expandedTaskIds.value = [...options.expandedTaskIds.value, task.id]
      }
      options.onPersist?.()
      return
    }
    options.onJumpToMessage?.(task)
  }

  async function controlTask(taskId: string, action: 'pause' | 'resume' | 'cancel' | 'retry' | 'approve'): Promise<void> {
    const task = options.taskList.value.find((item) => item.id === taskId)
    if (!task || task.type !== 'agent_task') return
    const runId = activeRunIdOfTask(task)
    if (!runId) return
    if (action === 'approve') {
      const snapshot = await agentRunsApi.getRun(runId)
      const grant = snapshot.approval?.grant
      if (!grant) throw new Error('任务当前没有可用的审批凭证')
      await agentRunsApi.continueRun(runId, { approval_grant: grant })
    } else if (action === 'pause') await agentRunsApi.pauseRun(runId)
    else if (action === 'resume') await agentRunsApi.resumeRun(runId)
    else if (action === 'retry') await agentRunsApi.retryRun(runId)
    else await agentRunsApi.cancelRun(runId)
    await refreshTasks()
  }

  async function archiveCompletedTasks(): Promise<void> {
    const completed = options.taskList.value.filter(
      (task) => task.type === 'agent_task' && ['success', 'failed', 'cancelled'].includes(task.status),
    )
    await Promise.all(
      completed.map(async (task) => {
        const taskId = String(task.payload?.taskId || '').trim()
        if (taskId) await agentRunsApi.archiveTask(taskId)
      }),
    )
    const archivedIds = new Set(completed.map((task) => task.id))
    options.taskList.value = options.taskList.value.filter((task) => !archivedIds.has(task.id))
    options.onPersist?.()
  }

  return {
    archiveCompletedTasks,
    controlTask,
    refreshTasks,
    selectTask,
    start,
    stop,
  }
}

import type { Ref } from 'vue'
import agentRunsApi from '@/api/agentRuns'
import type { TaskItem } from './useChatPersistence'
import {
  activeRunIdOfTask,
  conversationIdOfTask,
  groupAgentRunsIntoTasks,
} from '@/utils/agentTaskWorkspaceModel'

const ARCHIVED_TASKS_KEY = 'xcagi_agent_tasks_archived_v1'

function archivedTaskIds(): Set<string> {
  if (typeof localStorage === 'undefined') return new Set()
  try {
    const parsed = JSON.parse(localStorage.getItem(ARCHIVED_TASKS_KEY) || '[]')
    return new Set(Array.isArray(parsed) ? parsed.map(String) : [])
  } catch {
    return new Set()
  }
}

function persistArchivedTaskIds(ids: Set<string>): void {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem(ARCHIVED_TASKS_KEY, JSON.stringify([...ids].slice(-500)))
}

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
  let refreshInFlight = false

  async function refreshTasks(): Promise<void> {
    if (refreshInFlight) return
    refreshInFlight = true
    try {
      const response = await agentRunsApi.listRuns({ limit: 200 })
      const runs = Array.isArray(response?.data) ? response.data : []
      const archived = archivedTaskIds()
      const serverTasks = groupAgentRunsIntoTasks(runs).filter((task) => !archived.has(task.id))
      const localTasks = options.taskList.value.filter((task) => !['agent_task', 'agent_run'].includes(task.type))
      options.taskList.value = [...serverTasks, ...localTasks]
      const known = new Set(options.taskList.value.map((task) => task.id))
      options.expandedTaskIds.value = options.expandedTaskIds.value.filter((id) => known.has(id))
      if (!known.has(options.activeTaskId.value)) {
        options.activeTaskId.value = options.taskList.value[0]?.id || ''
      }
      options.sortTaskList()
      options.onPersist?.()
    } catch {
      // Keep the last durable snapshot in the panel while offline.
    } finally {
      refreshInFlight = false
    }
  }

  function start(): void {
    void refreshTasks()
    if (refreshTimer !== null) return
    refreshTimer = window.setInterval(() => void refreshTasks(), 4000)
  }

  function stop(): void {
    if (refreshTimer !== null) window.clearInterval(refreshTimer)
    refreshTimer = null
  }

  async function selectTask(task: TaskItem): Promise<void> {
    options.activeTaskId.value = task.id
    if (!options.expandedTaskIds.value.includes(task.id)) {
      options.expandedTaskIds.value = [...options.expandedTaskIds.value, task.id]
    }
    options.onPersist?.()
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

  async function controlTask(
    taskId: string,
    action: 'pause' | 'resume' | 'cancel' | 'retry' | 'approve',
  ): Promise<void> {
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

  function archiveCompletedTasks(): void {
    const archived = archivedTaskIds()
    options.taskList.value.forEach((task) => {
      if (
        task.type === 'agent_task'
        && ['success', 'failed', 'cancelled'].includes(task.status)
      ) {
        archived.add(task.id)
      }
    })
    persistArchivedTaskIds(archived)
    options.taskList.value = options.taskList.value.filter((task) => !archived.has(task.id))
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

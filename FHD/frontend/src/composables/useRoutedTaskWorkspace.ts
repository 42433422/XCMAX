import { computed, watch, type Ref } from 'vue'
import agentRunsApi from '@/api/agentRuns'
import type { AgentTaskSummary } from '@/api/agentRuns'
import type { TaskItem } from './useChatPersistence'
import { taskNeedsApproval, taskProgressPercent, taskStatusLabel, taskUnreadCount } from '@/utils/taskWorkspacePresentation'

export interface RoutedTaskWorkspaceProps {
  workspaceTaskId?: string
  workspaceConversationId?: string
}

interface RoutedTaskWorkspaceOptions {
  props: RoutedTaskWorkspaceProps
  currentSessionId: Ref<string>
  taskList: Ref<TaskItem[]>
  filteredTaskList: Ref<TaskItem[]>
  activeTaskId: Ref<string>
  taskSummaries?: Ref<AgentTaskSummary[]>
  loadSession: (conversationId: string) => Promise<void>
  markTaskRead?: (taskId: string) => Promise<void>
}

export function resolveWorkspaceSessionId(props: RoutedTaskWorkspaceProps): string {
  return String(props.workspaceConversationId || props.workspaceTaskId || '').trim()
}

export function useRoutedTaskWorkspace(options: RoutedTaskWorkspaceOptions) {
  const workspaceTaskId = computed(() => String(options.props.workspaceTaskId || '').trim())
  const workspaceMode = computed(() => Boolean(workspaceTaskId.value))
  const visibleTaskList = computed(() => {
    if (!workspaceTaskId.value) return options.taskList.value
    return options.taskList.value.filter((task) => String(task.payload?.taskId || '') === workspaceTaskId.value)
  })
  const visibleFilteredTaskList = computed(() => {
    if (!workspaceTaskId.value) return options.filteredTaskList.value
    const visibleIds = new Set(visibleTaskList.value.map((task) => task.id))
    return options.filteredTaskList.value.filter((task) => visibleIds.has(task.id))
  })
  const visibleActiveTaskId = computed(() => {
    if (!workspaceTaskId.value) return options.activeTaskId.value
    return visibleTaskList.value.some((task) => task.id === options.activeTaskId.value)
      ? options.activeTaskId.value
      : visibleTaskList.value[0]?.id || ''
  })
  const activeWorkspaceTask = computed(
    () => visibleTaskList.value.find((task) => task.id === visibleActiveTaskId.value) || visibleTaskList.value[0] || null,
  )
  const activeWorkspaceSummary = computed(() => options.taskSummaries?.value.find((task) => task.task_id === workspaceTaskId.value) || null)
  const workspaceHeader = computed(() => {
    const summary = activeWorkspaceSummary.value
    const localTask = activeWorkspaceTask.value
    const payload = localTask?.payload || {}
    const rawStatus = String(summary?.status || payload.rawRunStatus || localTask?.status || '')
    const summaryProgress = summary ? taskProgressPercent(summary) : undefined
    return {
      title: String(summary?.title || localTask?.title || workspaceTaskId.value),
      status: rawStatus,
      stage: String(summary?.progress?.stage || localTask?.stage || taskStatusLabel(rawStatus)),
      progress: summaryProgress ?? localTask?.progress,
      unreadCount: taskUnreadCount(summary),
      approvalRequired: taskNeedsApproval(summary),
      attempt: Number(summary?.attempt || payload.attempt || 1),
      runCount: Number(summary?.run_count || payload.runCount || 1),
      capabilities: (summary?.capabilities || payload.capabilities || {}) as Record<string, boolean>,
    }
  })

  watch(
    () => resolveWorkspaceSessionId(options.props),
    (conversationId) => {
      if (conversationId && conversationId !== options.currentSessionId.value) {
        void options.loadSession(conversationId)
      }
    },
  )
  watch(
    workspaceTaskId,
    (taskId) => {
      if (!taskId) return
      const markRead = options.markTaskRead ? options.markTaskRead(taskId) : agentRunsApi.markTaskRead(taskId).then(() => undefined)
      void markRead.catch(() => undefined)
    },
    { immediate: true },
  )

  return {
    activeWorkspaceTask,
    activeWorkspaceSummary,
    visibleActiveTaskId,
    visibleFilteredTaskList,
    visibleTaskList,
    workspaceMode,
    workspaceHeader,
    workspaceTaskId,
  }
}

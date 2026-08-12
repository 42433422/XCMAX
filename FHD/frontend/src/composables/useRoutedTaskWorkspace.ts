import { computed, watch, type Ref } from 'vue'
import agentRunsApi from '@/api/agentRuns'
import type { TaskItem } from './useChatPersistence'

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
  loadSession: (conversationId: string) => Promise<void>
}

export function resolveWorkspaceSessionId(props: RoutedTaskWorkspaceProps): string {
  return String(props.workspaceConversationId || props.workspaceTaskId || '').trim()
}

export function useRoutedTaskWorkspace(options: RoutedTaskWorkspaceOptions) {
  const workspaceTaskId = computed(() => String(options.props.workspaceTaskId || '').trim())
  const workspaceMode = computed(() => Boolean(workspaceTaskId.value))
  const visibleTaskList = computed(() => {
    if (!workspaceTaskId.value) return options.taskList.value
    return options.taskList.value.filter(
      (task) => String(task.payload?.taskId || '') === workspaceTaskId.value,
    )
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
      : (visibleTaskList.value[0]?.id || '')
  })
  const activeWorkspaceTask = computed(() => (
    visibleTaskList.value.find((task) => task.id === visibleActiveTaskId.value)
    || visibleTaskList.value[0]
    || null
  ))

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
      if (taskId) void agentRunsApi.markTaskRead(taskId).catch(() => undefined)
    },
    { immediate: true },
  )

  return {
    activeWorkspaceTask,
    visibleActiveTaskId,
    visibleFilteredTaskList,
    visibleTaskList,
    workspaceMode,
    workspaceTaskId,
  }
}

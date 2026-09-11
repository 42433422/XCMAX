import { watch, type Ref } from 'vue'
import { useModsStore } from '@/stores/mods'
import { useAccountProfileStore } from '@/stores/accountProfile'
import type { TaskItem } from './useChatPersistence'
import { useAgentTaskWorkspace } from './useAgentTaskWorkspace'

interface UseChatTaskRuntimeBridgeOptions {
  taskList: Ref<TaskItem[]>
  activeTaskId: Ref<string>
  expandedTaskIds: Ref<string[]>
  sortTaskList: () => void
  persist: () => void
  loadConversation: (conversationId: string) => Promise<void>
  newConversation: () => void
  jumpToMessage: (task: TaskItem) => void
  toggleExpanded: (taskId: string) => void
  clearLocalHistory: () => void
}

export function useChatTaskRuntimeBridge(options: UseChatTaskRuntimeBridgeOptions) {
  const workspace = useAgentTaskWorkspace({
    taskList: options.taskList,
    activeTaskId: options.activeTaskId,
    expandedTaskIds: options.expandedTaskIds,
    sortTaskList: options.sortTaskList,
    onPersist: options.persist,
    onOpenConversation: options.loadConversation,
    onJumpToMessage: options.jumpToMessage,
  })

  const mods = useModsStore()
  const account = useAccountProfileStore()
  let started = false
  let scopeVersion = 0
  function start(): void { started = true; workspace.start() }
  function stop(): void { scopeVersion += 1; started = false; workspace.stop() }
  watch(
    () => [mods.activeModId, account.tenantId, account.localUserId, account.marketUserId, account.impersonatingMarketUserId, account.accountKind],
    () => {
      scopeVersion += 1
      workspace.stop()
      options.taskList.value = []
      options.activeTaskId.value = ''
      options.expandedTaskIds.value = []
      if (started) workspace.start()
    },
    { flush: 'sync' },
  )

  async function loadSession(conversationId: string): Promise<void> {
    const requestedVersion = scopeVersion
    await options.loadConversation(conversationId)
    if (requestedVersion !== scopeVersion) return
    await workspace.refreshTasks()
  }

  function newConversation(): void {
    options.newConversation()
    void workspace.refreshTasks()
  }

  async function selectTask(task: TaskItem): Promise<void> {
    if (task.type === 'agent_task') await workspace.selectTask(task)
    else options.toggleExpanded(task.id)
  }

  async function controlTask(taskId: string, action: 'cancel' | 'retry'): Promise<void> {
    const task = options.taskList.value.find((item) => item.id === taskId)
    if (task?.type === 'agent_task') await workspace.controlTask(taskId, action)
  }

  async function clearTaskHistory(): Promise<void> {
    const requestedVersion = scopeVersion
    await workspace.archiveCompletedTasks()
    if (requestedVersion !== scopeVersion) return
    options.clearLocalHistory()
  }

  return {
    loadSession,
    newConversation,
    selectTask,
    cancelTaskById: (id: string) => controlTask(id, 'cancel'),
    retryTask: (id: string) => controlTask(id, 'retry'),
    pauseTask: (id: string) => workspace.controlTask(id, 'pause'),
    resumeTask: (id: string) => workspace.controlTask(id, 'resume'),
    approveTask: (id: string) => workspace.controlTask(id, 'approve'),
    clearTaskHistory,
    refreshTasks: workspace.refreshTasks,
    start,
    stop,
  }
}

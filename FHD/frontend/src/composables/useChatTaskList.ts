import { ref, computed, type Ref } from 'vue'
import {
  TASK_HISTORY_LIMIT,
  type TaskItem,
  type TaskStatus,
} from './useChatPersistence'

export type { TaskItem, TaskStatus }

export interface UseChatTaskListOptions {
  onPersist?: () => void
  chatMessagesRef?: Ref<HTMLElement | null>
}

export function useChatTaskList(options: UseChatTaskListOptions = {}) {
  const { onPersist, chatMessagesRef } = options

  const taskList = ref<TaskItem[]>([])
  const activeTaskId = ref<string>('')
  const expandedTaskIds = ref<string[]>([])
  const taskFilter = ref<'all' | 'running' | 'success' | 'failed'>('all')

  function createTaskId(prefix: string): string {
    return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
  }

  function sortTaskList() {
    taskList.value.sort((a, b) => {
      const rank = (s: TaskStatus) => (s === 'running' ? 0 : s === 'queued' ? 1 : s === 'failed' ? 2 : s === 'success' ? 3 : 4)
      const r = rank(a.status) - rank(b.status)
      if (r !== 0) return r
      const startedDiff = (a.startedAt || 0) - (b.startedAt || 0)
      if (startedDiff !== 0) return startedDiff
      return a.id.localeCompare(b.id)
    })
    if (taskList.value.length > TASK_HISTORY_LIMIT) {
      taskList.value = taskList.value.slice(0, TASK_HISTORY_LIMIT)
    }
  }

  function upsertTask(partial: Partial<TaskItem> & { id: string; title: string; source: TaskItem['source']; type: string }) {
    const now = Date.now()
    const idx = taskList.value.findIndex((t) => t.id === partial.id)
    if (idx === -1) {
      taskList.value.unshift({
        id: partial.id,
        title: partial.title,
        type: partial.type,
        source: partial.source,
        status: partial.status || 'queued',
        progress: partial.progress,
        stage: partial.stage,
        summary: partial.summary,
        error: partial.error,
        startedAt: partial.startedAt || now,
        updatedAt: now,
        messageRef: partial.messageRef,
        payload: partial.payload || {},
      })
    } else {
      const current = taskList.value[idx]
      taskList.value[idx] = {
        ...current,
        ...partial,
        payload: { ...(current.payload || {}), ...(partial.payload || {}) },
        updatedAt: now,
      } as TaskItem
    }
    if (!activeTaskId.value) activeTaskId.value = partial.id
    sortTaskList()
    onPersist?.()
  }

  function finishTask(id: string, summary: string = '') {
    const task = taskList.value.find((t) => t.id === id)
    if (!task) return
    upsertTask({
      id,
      title: task.title,
      type: task.type,
      source: task.source,
      status: 'success',
      progress: 100,
      summary: summary || task.summary,
    })
  }

  function failTask(id: string, error: string) {
    const task = taskList.value.find((t) => t.id === id)
    if (!task) return
    upsertTask({
      id,
      title: task.title,
      type: task.type,
      source: task.source,
      status: 'failed',
      error,
    })
  }

  function cancelTaskById(id: string) {
    const task = taskList.value.find((t) => t.id === id)
    if (!task) return
    upsertTask({
      id,
      title: task.title,
      type: task.type,
      source: task.source,
      status: 'cancelled',
      summary: '任务已取消',
    })
  }

  function retryTask(id: string) {
    const task = taskList.value.find((t) => t.id === id)
    if (!task) return
    upsertTask({
      id,
      title: `${task.title}（重试）`,
      type: task.type,
      source: task.source,
      status: 'running',
      progress: 0,
      error: '',
    })
  }

  function toggleTaskExpanded(id: string) {
    if (expandedTaskIds.value.includes(id)) {
      expandedTaskIds.value = expandedTaskIds.value.filter((x) => x !== id)
    } else {
      expandedTaskIds.value = [...expandedTaskIds.value, id]
    }
  }

  const activeTask = computed(() => taskList.value.find((t) => t.id === activeTaskId.value) || null)

  const filteredTaskList = computed(() => {
    const list = taskList.value
    const wfPersistent = list.filter((t) => t.type === 'workflow_employee' && t.status === 'running')
    if (taskFilter.value === 'all') return list
    if (taskFilter.value === 'running') {
      return list.filter((t) => t.status === 'running' || t.status === 'queued')
    }
    if (taskFilter.value === 'success') {
      const rest = list.filter((t) => t.status === 'success')
      const ids = new Set(rest.map((t) => t.id))
      const wfExtra = wfPersistent.filter((t) => !ids.has(t.id))
      return [...wfExtra, ...rest]
    }
    const rest = list.filter((t) => t.status === 'failed' || t.status === 'cancelled')
    const ids = new Set(rest.map((t) => t.id))
    const wfExtra = wfPersistent.filter((t) => !ids.has(t.id))
    return [...wfExtra, ...rest]
  })

  function setTaskFilter(filter: 'all' | 'running' | 'success' | 'failed') {
    taskFilter.value = filter
  }

  function clearTaskHistory() {
    taskList.value = taskList.value.filter((t) => t.status === 'running' || t.status === 'queued')
    expandedTaskIds.value = expandedTaskIds.value.filter((id) => taskList.value.some((t) => t.id === id))
    onPersist?.()
  }

  function jumpToTaskMessage(task: TaskItem) {
    const refKey = String(task?.messageRef || '').trim()
    const index = Number(refKey)
    if (!Number.isFinite(index) || !chatMessagesRef?.value) return
    const nodes = chatMessagesRef.value.querySelectorAll('.message')
    const target = nodes[index] as HTMLElement | undefined
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }

  return {
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    activeTask,
    filteredTaskList,
    createTaskId,
    sortTaskList,
    upsertTask,
    finishTask,
    failTask,
    cancelTaskById,
    retryTask,
    toggleTaskExpanded,
    setTaskFilter,
    clearTaskHistory,
    jumpToTaskMessage,
  }
}

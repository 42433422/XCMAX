import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import agentRunsApi from '@/api/agentRuns'
import type {
  AgentRun,
  AgentTaskRuntime,
  AgentTaskSummary,
} from '@/api/agentRuns'
import { buildFullApiUrl } from '@/api/core'

const TERMINAL_STATES = new Set(['completed', 'failed', 'cancelled'])
type TaskControlAction = 'approve' | 'pause' | 'cancel' | 'resume' | 'retry'

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return '工作区列表暂时不可用'
}

export const useAgentTaskCenterStore = defineStore('agentTaskCenter', () => {
  const tasks = ref<AgentTaskSummary[]>([])
  const selectedTask = ref<AgentTaskSummary | null>(null)
  const selectedTaskId = ref('')
  const drawerOpen = ref(false)
  const loading = ref(false)
  const actionPending = ref('')
  const connected = ref(false)
  const error = ref('')
  const runtime = ref<AgentTaskRuntime>({ running: false, max_workers: 4, active_count: 0 })
  let stream: EventSource | null = null
  let reconnectTimer: number | null = null
  let fallbackTimer: number | null = null
  let started = false

  const attentionCount = computed(() =>
    tasks.value.filter((task) => ['waiting_user', 'blocked', 'failed'].includes(task.status)).length,
  )
  const unreadCount = computed(() =>
    tasks.value.reduce((total, task) => total + Math.max(
      0,
      Number(task.unread_count ?? (task.attention_state === 'result_unread' ? 1 : 0)) || 0,
    ), 0),
  )
  const approvalCount = computed(() =>
    tasks.value.filter((task) => task.approval_required || task.attention_state === 'approval_required' || task.status === 'waiting_user').length,
  )
  const activeCount = computed(() =>
    tasks.value.filter((task) => ['queued', 'planning', 'running', 'retrying', 'paused'].includes(task.status)).length,
  )

  function replaceTasks(snapshot: AgentTaskSummary[]): void {
    tasks.value = Array.isArray(snapshot) ? snapshot : []
    if (!selectedTaskId.value) return
    const summary = tasks.value.find((task) => task.task_id === selectedTaskId.value)
    if (summary && !selectedTask.value?.runs?.length) selectedTask.value = summary
    if (!summary && !selectedTask.value) selectedTaskId.value = ''
  }

  async function refresh(): Promise<void> {
    if (loading.value) return
    loading.value = true
    try {
      const [taskResponse, runtimeResponse] = await Promise.all([
        agentRunsApi.listTasks({ limit: 200 }),
        agentRunsApi.getTaskRuntime(),
      ])
      replaceTasks(Array.isArray(taskResponse.data) ? taskResponse.data : [])
      if (runtimeResponse.data) runtime.value = runtimeResponse.data
      error.value = ''
    } catch (reason) {
      error.value = errorMessage(reason)
    } finally {
      loading.value = false
    }
  }

  async function refreshDetail(): Promise<void> {
    if (!selectedTaskId.value) return
    try {
      const response = await agentRunsApi.getTask(selectedTaskId.value)
      selectedTask.value = response.data || null
      error.value = ''
    } catch (reason) {
      error.value = errorMessage(reason)
    }
  }

  async function openTask(taskId: string): Promise<void> {
    selectedTaskId.value = taskId
    drawerOpen.value = true
    selectedTask.value = tasks.value.find((task) => task.task_id === taskId) || null
    await refreshDetail()
  }

  async function markTaskRead(taskId: string): Promise<void> {
    const id = String(taskId || '').trim()
    if (!id) return
    try {
      const response = await agentRunsApi.markTaskRead(id)
      const updated = response.data
      if (updated) {
        tasks.value = tasks.value.map((task) => task.task_id === id ? { ...task, ...updated } : task)
        if (selectedTaskId.value === id) selectedTask.value = updated
      }
      error.value = ''
    } catch (reason) {
      error.value = errorMessage(reason)
    }
  }

  function closeDrawer(): void {
    drawerOpen.value = false
  }

  function showTaskList(): void {
    selectedTask.value = null
    selectedTaskId.value = ''
  }

  function activeRunOf(task: AgentTaskSummary | null): AgentRun | null {
    if (!task) return null
    if (task.active_run) return task.active_run
    const runs = task.runs || []
    return runs.find((run) => run.run_id === task.active_run_id) || runs[runs.length - 1] || null
  }

  async function applyControl(task: AgentTaskSummary, action: TaskControlAction): Promise<void> {
    const runId = activeRunOf(task)?.run_id || task.active_run_id
    if (!runId) throw new Error('工作区当前没有可控制的运行')
    if (action === 'approve') {
      const snapshot = await agentRunsApi.getRun(runId)
      const grant = snapshot.approval?.grant
      if (!grant) throw new Error('任务当前没有可用的审批凭证')
      await agentRunsApi.continueRun(runId, { approval_grant: grant })
    } else if (action === 'pause') await agentRunsApi.pauseRun(runId)
    else if (action === 'cancel') await agentRunsApi.cancelRun(runId)
    else if (action === 'resume') await agentRunsApi.resumeRun(runId)
    else await agentRunsApi.retryRun(runId)
  }

  async function controlTask(taskId: string, action: TaskControlAction): Promise<void> {
    const id = String(taskId || '').trim()
    if (!id || actionPending.value) return
    actionPending.value = action
    try {
      const response = await agentRunsApi.getTask(id)
      const task = response.data
      if (!task) throw new Error('工作区任务不存在')
      await applyControl(task, action)
      await Promise.all([refresh(), selectedTaskId.value ? refreshDetail() : Promise.resolve()])
    } catch (reason) {
      error.value = errorMessage(reason)
    } finally {
      actionPending.value = ''
    }
  }

  async function control(action: TaskControlAction): Promise<void> {
    const task = selectedTask.value
    if (!task || actionPending.value) return
    actionPending.value = action
    try {
      await applyControl(task, action)
      await Promise.all([refresh(), refreshDetail()])
    } catch (reason) {
      error.value = errorMessage(reason)
    } finally {
      actionPending.value = ''
    }
  }

  async function archiveSelected(): Promise<void> {
    const task = selectedTask.value
    if (!task || !TERMINAL_STATES.has(task.status) || actionPending.value) return
    actionPending.value = 'archive'
    try {
      await agentRunsApi.archiveTask(task.task_id)
      selectedTask.value = null
      selectedTaskId.value = ''
      await refresh()
    } catch (reason) {
      error.value = errorMessage(reason)
    } finally {
      actionPending.value = ''
    }
  }

  function connectStream(): void {
    if (!started || typeof window === 'undefined' || typeof EventSource === 'undefined') return
    stream?.close()
    stream = new EventSource(buildFullApiUrl(agentRunsApi.taskEventStreamPath()), {
      withCredentials: true,
    })
    stream.addEventListener('task.snapshot', (event) => {
      try {
        replaceTasks(JSON.parse((event as MessageEvent).data) as AgentTaskSummary[])
        connected.value = true
        error.value = ''
        if (drawerOpen.value && selectedTaskId.value) void refreshDetail()
        void agentRunsApi.getTaskRuntime().then((response) => {
          if (response.data) runtime.value = response.data
        })
      } catch {
        error.value = '任务快照格式无效'
      }
    })
    stream.addEventListener('stream.closed', () => {
      connected.value = false
      scheduleReconnect()
    })
    stream.onerror = () => {
      connected.value = false
      stream?.close()
      scheduleReconnect()
    }
  }

  function scheduleReconnect(): void {
    if (!started || reconnectTimer !== null || typeof window === 'undefined') return
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      connectStream()
    }, 1500)
  }

  function start(): void {
    if (started) return
    started = true
    void refresh()
    connectStream()
    if (typeof window !== 'undefined') {
      fallbackTimer = window.setInterval(() => void refresh(), 15000)
    }
  }

  function stop(): void {
    started = false
    connected.value = false
    stream?.close()
    stream = null
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
    if (fallbackTimer !== null) window.clearInterval(fallbackTimer)
    reconnectTimer = null
    fallbackTimer = null
  }

  return {
    tasks,
    selectedTask,
    selectedTaskId,
    drawerOpen,
    loading,
    actionPending,
    connected,
    error,
    runtime,
    attentionCount,
    unreadCount,
    approvalCount,
    activeCount,
    archiveSelected,
    closeDrawer,
    control,
    controlTask,
    markTaskRead,
    openTask,
    refresh,
    refreshDetail,
    showTaskList,
    start,
    stop,
  }
})

import { AuthenticatedEventStream } from '@/utils/authenticatedEventStream'
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import agentRunsApi from '@/api/agentRuns'
import { approveRunWithFreshGrant } from '@/api/agentRunApproval'
import type { AgentRun, AgentTaskRuntime, AgentTaskSummary } from '@/api/agentRuns'
import { buildFullApiUrl } from '@/api/core'
import { taskEmployeeIds } from '@/utils/workflowEmployeeTaskState'
import { taskStatusOf } from '@/utils/taskWorkspacePresentation'

const TERMINAL_STATES = new Set(['completed', 'failed', 'cancelled'])
let sessionUnauthorizedBound = false
type TaskControlAction = 'approve' | 'pause' | 'cancel' | 'resume' | 'retry'

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return '工作区列表暂时不可用'
}

function isUnauthorized(error: unknown): boolean {
  const status = Number((error as { status?: number } | null)?.status || 0)
  return status === 401 || status === 403
}

function mergeTaskSnapshot(incoming: AgentTaskSummary, known?: AgentTaskSummary | null): AgentTaskSummary {
  if (known?.task_id === incoming.task_id) {
    if (
      known.attempt > incoming.attempt ||
      (known.attempt === incoming.attempt && Date.parse(known.updated_at || '') > Date.parse(incoming.updated_at || ''))
    )
      return known
  }
  if (known?.task_id === incoming.task_id && known.active_run_id === incoming.active_run_id && !taskEmployeeIds(incoming).length) {
    const ids = taskEmployeeIds(known)
    if (ids.length)
      incoming = { ...incoming, metadata: { ...incoming.metadata, employee_ids: ids, employee_id: ids.length === 1 ? ids[0] : '' } }
  }
  if (
    known?.progress?.basis !== 'files' ||
    known.task_id !== incoming.task_id ||
    !incoming.active_run_id ||
    known.active_run_id !== incoming.active_run_id
  )
    return incoming
  if (incoming.progress?.basis === 'files') {
    const knownAt = Date.parse(known.progress.updated_at || '')
    const incomingAt = Date.parse(incoming.progress.updated_at || '')
    if (!(knownAt > incomingAt)) return incoming
  }
  return { ...incoming, progress: known.progress }
}

export const useAgentTaskCenterStore = defineStore('agentTaskCenter', () => {
  const tasks = ref<AgentTaskSummary[]>([])
  const selectedTask = ref<AgentTaskSummary | null>(null)
  const selectedTaskId = ref('')
  const drawerOpen = ref(false)
  const loading = ref(false)
  const actionPending = ref('')
  const connected = ref(false)
  const stale = ref(true)
  const lastVerifiedAt = ref(0)
  const error = ref('')
  const runtime = ref<AgentTaskRuntime>({ running: false, max_workers: 4, active_count: 0 })
  let stream: AuthenticatedEventStream | null = null
  let reconnectTimer: number | null = null
  let fallbackTimer: number | null = null
  let started = false
  let authPaused = false
  let scopeVersion = 0
  let detailRequestVersion = 0
  let snapshotRevision = 0
  let refreshInFlight: Promise<void> | null = null

  const attentionCount = computed(() => tasks.value.filter((task) => ['waiting_user', 'blocked', 'failed', 'unknown'].includes(taskStatusOf(task))).length)
  const unreadCount = computed(() =>
    tasks.value.reduce(
      (total, task) => total + Math.max(0, Number(task.unread_count ?? (task.attention_state === 'result_unread' ? 1 : 0)) || 0),
      0,
    ),
  )
  const approvalCount = computed(
    () =>
      tasks.value.filter((task) => task.approval_required || task.attention_state === 'approval_required' || task.status === 'waiting_user')
        .length,
  )
  const activeCount = computed(
    () => tasks.value.filter((task) => ['queued', 'planning', 'running', 'retrying', 'paused'].includes(task.status)).length,
  )

  function replaceTasks(snapshot: AgentTaskSummary[]): void {
    if (
      !Array.isArray(snapshot) ||
      snapshot.some((task) => !task || typeof task.task_id !== 'string' || !task.task_id || typeof task.status !== 'string')
    ) {
      throw new Error('任务快照格式无效')
    }
    snapshotRevision += 1
    stale.value = false
    lastVerifiedAt.value = Date.now()
    const previous = new Map(tasks.value.map((task) => [task.task_id, task]))
    tasks.value = snapshot.map((task) => mergeTaskSnapshot(mergeTaskSnapshot(task, previous.get(task.task_id)), selectedTask.value))
    if (!selectedTaskId.value) return
    const summary = tasks.value.find((task) => task.task_id === selectedTaskId.value)
    if (summary) {
      const detail = selectedTask.value
      if (!detail?.runs?.length || detail.active_run_id !== summary.active_run_id) selectedTask.value = summary
      else
        selectedTask.value = {
          ...detail,
          ...summary,
          runs: detail.runs,
          active_run: summary.active_run || detail.active_run,
          capabilities: Object.keys(summary.capabilities || {}).length ? summary.capabilities : detail.capabilities,
        }
    }
    if (!summary && !selectedTask.value) selectedTaskId.value = ''
  }

  async function refresh(afterAction = false): Promise<void> {
    const requestedScopeVersion = scopeVersion
    while (refreshInFlight) {
      await refreshInFlight
      if (!afterAction || requestedScopeVersion !== scopeVersion) return
    }
    const requestedRevision = snapshotRevision
    loading.value = true
    const request = (async () => {
      try {
        const [taskResponse, runtimeResponse] = await Promise.all([agentRunsApi.listTasks({ limit: 200 }), agentRunsApi.getTaskRuntime()])
        if (requestedScopeVersion !== scopeVersion) return
        if (
          taskResponse.success === false ||
          !Array.isArray(taskResponse.data) ||
          runtimeResponse.success === false ||
          !runtimeResponse.data
        ) {
          throw new Error('任务状态读取失败，保留上次记录，请刷新核对')
        }
        // A slower HTTP response must not erase an already-applied stream update.
        if (requestedRevision === snapshotRevision) {
          replaceTasks(taskResponse.data)
          runtime.value = runtimeResponse.data
          error.value = ''
        } else {
          // Older stored tasks may lack the identity projection until their next write.
          // Enrich matching runs from the detail response without losing newer tasks.
          const details = new Map(taskResponse.data.map((task) => [task.task_id, task]))
          tasks.value = tasks.value.map((task) => mergeTaskSnapshot(task, details.get(task.task_id)))
        }
      } catch (reason) {
        if (requestedScopeVersion !== scopeVersion) return
        if (isUnauthorized(reason)) {
          pauseForLoggedOutSession()
          return
        }
        if (requestedRevision !== snapshotRevision) return
        error.value = errorMessage(reason)
        stale.value = true
      } finally {
        if (requestedScopeVersion === scopeVersion) loading.value = false
      }
    })()
    refreshInFlight = request
    try {
      await request
    } finally {
      if (refreshInFlight === request) refreshInFlight = null
    }
  }

  async function refreshDetail(): Promise<void> {
    if (!selectedTaskId.value) return
    const requestedTaskId = selectedTaskId.value
    const requestedScopeVersion = scopeVersion
    const requestVersion = ++detailRequestVersion
    const isCurrent = () =>
      requestedScopeVersion === scopeVersion && requestedTaskId === selectedTaskId.value && requestVersion === detailRequestVersion
    try {
      const response = await agentRunsApi.getTask(requestedTaskId)
      if (!isCurrent()) return
      if (response.success === false || !response.data) throw new Error('任务详情读取失败，请刷新核对')
      const summary = tasks.value.find((task) => task.task_id === requestedTaskId)
      selectedTask.value = mergeTaskSnapshot(mergeTaskSnapshot(response.data, summary), selectedTask.value)
      error.value = ''
    } catch (reason) {
      if (!isCurrent()) return
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
    const requestedScopeVersion = scopeVersion
    try {
      const response = await agentRunsApi.markTaskRead(id)
      if (requestedScopeVersion !== scopeVersion) return
      const updated = response.data
      if (updated) {
        const summary = tasks.value.find((task) => task.task_id === id)
        if (summary?.active_run_id && summary.active_run_id !== updated.active_run_id) return
        const task = mergeTaskSnapshot(mergeTaskSnapshot(updated, summary), selectedTask.value)
        tasks.value = tasks.value.map((current) => (current.task_id === id ? { ...current, ...task } : current))
        if (selectedTaskId.value === id) selectedTask.value = task
      }
      error.value = ''
    } catch (reason) {
      if (requestedScopeVersion !== scopeVersion) return
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

  async function applyControl(task: AgentTaskSummary, action: TaskControlAction, requestedScopeVersion: number): Promise<void> {
    if (requestedScopeVersion !== scopeVersion) return
    const runId = activeRunOf(task)?.run_id || task.active_run_id
    if (!runId) throw new Error('工作区当前没有可控制的运行')
    const result =
      action === 'approve'
        ? await approveRunWithFreshGrant(runId, { isCurrent: () => requestedScopeVersion === scopeVersion })
        : await {
            pause: agentRunsApi.pauseRun,
            cancel: agentRunsApi.cancelRun,
            resume: agentRunsApi.resumeRun,
            retry: agentRunsApi.retryRun,
          }[action](runId)
    if (result?.success === false) throw new Error(result.message || '任务操作未被服务端接受')
  }

  async function controlTask(taskId: string, action: TaskControlAction): Promise<void> {
    const id = String(taskId || '').trim()
    if (!id || actionPending.value) return
    const requestedScopeVersion = scopeVersion
    actionPending.value = action
    error.value = ''
    try {
      const response = await agentRunsApi.getTask(id)
      if (requestedScopeVersion !== scopeVersion) return
      const task = response.data
      if (response.success === false || !task) throw new Error('工作区任务不存在或状态读取失败')
      await applyControl(task, action, requestedScopeVersion)
      if (requestedScopeVersion !== scopeVersion) return
      await refresh(true)
      if (requestedScopeVersion !== scopeVersion) return
      if (stale.value) throw new Error('操作已提交，但当前状态无法核实；请刷新核对，勿重复提交')
      if (selectedTaskId.value) await refreshDetail()
    } catch (reason) {
      if (requestedScopeVersion !== scopeVersion) return
      error.value = errorMessage(reason)
      stale.value = true
    } finally {
      if (requestedScopeVersion === scopeVersion) actionPending.value = ''
    }
  }

  async function control(action: TaskControlAction): Promise<void> {
    if (selectedTask.value) await controlTask(selectedTask.value.task_id, action)
  }

  async function archiveSelected(): Promise<void> {
    const task = selectedTask.value
    if (!task || !TERMINAL_STATES.has(task.status) || actionPending.value) return
    const requestedScopeVersion = scopeVersion
    actionPending.value = 'archive'
    try {
      await agentRunsApi.archiveTask(task.task_id)
      if (requestedScopeVersion !== scopeVersion) return
      selectedTask.value = null
      selectedTaskId.value = ''
      await refresh()
    } catch (reason) {
      if (requestedScopeVersion !== scopeVersion) return
      error.value = errorMessage(reason)
    } finally {
      if (requestedScopeVersion === scopeVersion) actionPending.value = ''
    }
  }

  function connectStream(): void {
    if (!started || typeof window === 'undefined' || typeof fetch === 'undefined') return
    stream?.close()
    stream = new AuthenticatedEventStream(buildFullApiUrl(agentRunsApi.taskEventStreamPath()))
    const connection = stream
    const requestedScopeVersion = scopeVersion
    const isCurrent = () => started && stream === connection && requestedScopeVersion === scopeVersion
    stream.addEventListener('task.snapshot', (event) => {
      if (!isCurrent()) return
      try {
        replaceTasks(JSON.parse((event as MessageEvent).data) as AgentTaskSummary[])
        connected.value = true
        error.value = ''
        if (drawerOpen.value && selectedTaskId.value) void refreshDetail()
        void agentRunsApi
          .getTaskRuntime()
          .then((response) => {
            if (isCurrent() && response.data) runtime.value = response.data
          })
          .catch(() => {
            /* Polling retains the last scoped runtime snapshot. */
          })
      } catch {
        error.value = '任务快照格式无效'
        stale.value = true
      }
    })
    stream.addEventListener('stream.unauthorized', () => {
      if (!isCurrent()) return
      pauseForLoggedOutSession()
    })
    stream.addEventListener('stream.closed', () => {
      if (!isCurrent()) return
      connected.value = false
      stale.value = true
      stream?.close()
      stream = null
      scheduleReconnect()
    })
    stream.onerror = () => {
      if (!isCurrent()) return
      connected.value = false
      stale.value = true
      stream?.close()
      stream = null
      scheduleReconnect()
    }
  }

  function pauseForLoggedOutSession(): void {
    if (authPaused) return
    authPaused = true
    scopeVersion += 1
    error.value = ''
    tasks.value = []
    selectedTask.value = null
    selectedTaskId.value = ''
    loading.value = false
    actionPending.value = ''
    lastVerifiedAt.value = 0
    refreshInFlight = null
    stop()
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('xcagi:session-unauthorized'))
    }
  }

  function scheduleReconnect(): void {
    if (!started || authPaused || reconnectTimer !== null || typeof window === 'undefined') return
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      connectStream()
    }, 1500)
  }

  function resumeAfterLogin(): void {
    authPaused = false
    start()
  }

  function start(): void {
    if (started || authPaused) return
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
    stale.value = true
    stream?.close()
    stream = null
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
    if (fallbackTimer !== null) window.clearInterval(fallbackTimer)
    reconnectTimer = null
    fallbackTimer = null
  }

  function restartForScope(): void {
    const shouldRestart = started
    stop()
    scopeVersion += 1
    refreshInFlight = null
    snapshotRevision += 1
    lastVerifiedAt.value = 0
    actionPending.value = ''
    tasks.value = []
    selectedTask.value = null
    selectedTaskId.value = ''
    runtime.value = { running: false, max_workers: 4, active_count: 0 }
    loading.value = false
    error.value = ''
    if (shouldRestart) start()
  }

  if (typeof window !== 'undefined' && !sessionUnauthorizedBound) {
    sessionUnauthorizedBound = true
    window.addEventListener('xcagi:session-unauthorized', () => pauseForLoggedOutSession())
  }

  return {
    tasks,
    selectedTask,
    selectedTaskId,
    drawerOpen,
    loading,
    actionPending,
    connected,
    stale,
    lastVerifiedAt,
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
    restartForScope,
    resumeAfterLogin,
    showTaskList,
    start,
    stop,
  }
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => ({
  listTasks: vi.fn(),
  getTaskRuntime: vi.fn(),
  getTask: vi.fn(),
  getRun: vi.fn(),
  continueRun: vi.fn(),
  pauseRun: vi.fn(),
  cancelRun: vi.fn(),
  resumeRun: vi.fn(),
  retryRun: vi.fn(),
  archiveTask: vi.fn(),
  taskEventStreamPath: vi.fn(() => '/api/agent/tasks/events/stream'),
}))

vi.mock('@/api/agentRuns', () => ({ default: apiMock }))
vi.mock('@/api/core', () => ({ buildFullApiUrl: (path: string) => path }))

import { useAgentTaskCenterStore } from './agentTaskCenter'

const task = {
  task_id: 'task-1', user_id: 'owner', title: '并发库存核对', source: 'agent', task_type: 'agent',
  status: 'waiting_user', attempt: 1, run_count: 1, active_run_id: 'run-1',
  capabilities: { approve: true, pause: true, cancel: true, retry: false, resume: false, evidence: true },
  active_run: { run_id: 'run-1', user_id: 'owner', message: '核对库存', status: 'waiting_user' },
}

describe('agent task center store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.listTasks.mockResolvedValue({ success: true, data: [task] })
    apiMock.getTaskRuntime.mockResolvedValue({
      success: true,
      data: { running: true, max_workers: 4, active_count: 2 },
    })
    apiMock.getTask.mockResolvedValue({ success: true, data: task })
    apiMock.getRun.mockResolvedValue({ success: true, data: task.active_run, approval: { grant: 'grant-1' } })
    apiMock.continueRun.mockResolvedValue({ success: true, data: { ...task.active_run, status: 'queued' } })
    apiMock.pauseRun.mockResolvedValue({ success: true, data: task.active_run })
    apiMock.cancelRun.mockResolvedValue({ success: true, data: task.active_run })
    apiMock.resumeRun.mockResolvedValue({ success: true, data: task.active_run })
    apiMock.retryRun.mockResolvedValue({ success: true, data: task.active_run })
    apiMock.archiveTask.mockResolvedValue({ success: true, data: task })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads independent task state and approves through the durable run contract', async () => {
    const store = useAgentTaskCenterStore()
    await store.refresh()

    expect(store.tasks).toHaveLength(1)
    expect(store.attentionCount).toBe(1)
    expect(store.runtime).toEqual({ running: true, max_workers: 4, active_count: 2 })

    await store.openTask('task-1')
    store.showTaskList()
    expect(store.selectedTaskId).toBe('')
    expect(store.selectedTask).toBeNull()

    await store.openTask('task-1')
    await store.control('approve')

    expect(apiMock.getRun).toHaveBeenCalledWith('run-1')
    expect(apiMock.continueRun).toHaveBeenCalledWith('run-1', { approval_grant: 'grant-1' })
    expect(apiMock.listTasks).toHaveBeenCalledTimes(2)
    expect(apiMock.getTask).toHaveBeenCalledTimes(3)
  })

  it('replaces the task list from the authenticated SSE snapshot', async () => {
    class FakeEventSource {
      static instances: FakeEventSource[] = []
      listeners = new Map<string, (event: MessageEvent) => void>()
      onerror: (() => void) | null = null
      closed = false

      constructor(public url: string) {
        FakeEventSource.instances.push(this)
      }

      addEventListener(type: string, listener: (event: MessageEvent) => void): void {
        this.listeners.set(type, listener)
      }

      emit(type: string, data: unknown): void {
        this.listeners.get(type)?.(new MessageEvent(type, { data: JSON.stringify(data) }))
      }

      close(): void {
        this.closed = true
      }
    }
    vi.stubGlobal('EventSource', FakeEventSource)
    const store = useAgentTaskCenterStore()

    store.start()
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    FakeEventSource.instances[0].emit('task.snapshot', [
      { ...task, status: 'completed', attention_state: 'result_unread' },
    ])

    expect(FakeEventSource.instances[0].url).toBe('/api/agent/tasks/events/stream')
    expect(store.connected).toBe(true)
    expect(store.tasks[0].status).toBe('completed')
    expect(store.attentionCount).toBe(0)
    store.stop()
    expect(FakeEventSource.instances[0].closed).toBe(true)
  })

  it('handles refresh and detail failures without losing durable state', async () => {
    const store = useAgentTaskCenterStore()
    store.loading = true
    await store.refresh()
    expect(apiMock.listTasks).not.toHaveBeenCalled()

    store.loading = false
    apiMock.listTasks.mockRejectedValueOnce(new Error('任务加载失败'))
    await store.refresh()
    expect(store.error).toBe('任务加载失败')
    expect(store.loading).toBe(false)

    await store.refreshDetail()
    expect(apiMock.getTask).not.toHaveBeenCalled()
    store.selectedTaskId = 'missing-task'
    apiMock.getTask.mockRejectedValueOnce('offline')
    await store.refreshDetail()
    expect(store.error).toBe('任务中心暂时不可用')
  })

  it('normalizes sparse API payloads and task selections', async () => {
    const store = useAgentTaskCenterStore()
    store.selectedTaskId = 'stale-task'
    store.selectedTask = null
    apiMock.listTasks.mockResolvedValueOnce({ success: true, data: { invalid: true } })
    apiMock.getTaskRuntime.mockResolvedValueOnce({ success: true })
    await store.refresh()

    expect(store.tasks).toEqual([])
    expect(store.selectedTaskId).toBe('')
    expect(store.runtime).toEqual({ running: false, max_workers: 4, active_count: 0 })

    apiMock.getTask.mockResolvedValueOnce({ success: true })
    store.selectedTaskId = 'empty-detail'
    await store.refreshDetail()
    expect(store.selectedTask).toBeNull()

    await store.openTask('not-in-list')
    expect(store.drawerOpen).toBe(true)
    store.closeDrawer()
    expect(store.drawerOpen).toBe(false)

    store.selectedTask = null
    await store.control('pause')
    store.selectedTask = { ...task, active_run_id: undefined, active_run: undefined, runs: undefined }
    await store.control('pause')
    expect(apiMock.pauseRun).not.toHaveBeenCalled()
  })

  it('dispatches every durable lifecycle command and clears pending state', async () => {
    const store = useAgentTaskCenterStore()
    store.selectedTask = task

    await store.control('pause')
    await store.control('cancel')
    await store.control('resume')
    await store.control('retry')

    expect(apiMock.pauseRun).toHaveBeenCalledWith('run-1')
    expect(apiMock.cancelRun).toHaveBeenCalledWith('run-1')
    expect(apiMock.resumeRun).toHaveBeenCalledWith('run-1')
    expect(apiMock.retryRun).toHaveBeenCalledWith('run-1')
    expect(store.actionPending).toBe('')

    apiMock.pauseRun.mockRejectedValueOnce(new Error('暂停失败'))
    await store.control('pause')
    expect(store.error).toBe('暂停失败')
    expect(store.actionPending).toBe('')
  })

  it('fails closed when approval has no grant and ignores missing runs', async () => {
    const store = useAgentTaskCenterStore()
    store.selectedTask = { ...task, active_run_id: undefined, active_run: undefined, runs: [] }
    await store.control('pause')
    expect(apiMock.pauseRun).not.toHaveBeenCalled()

    store.selectedTask = { ...task, active_run: undefined, runs: [task.active_run] }
    apiMock.getRun.mockResolvedValueOnce({ success: true, data: task.active_run })
    await store.control('approve')
    expect(apiMock.continueRun).not.toHaveBeenCalled()
    expect(store.error).toBe('任务当前没有可用的审批凭证')
  })

  it('archives only terminal tasks and reports archive failures', async () => {
    const store = useAgentTaskCenterStore()
    store.selectedTask = { ...task, status: 'running' }
    await store.archiveSelected()
    expect(apiMock.archiveTask).not.toHaveBeenCalled()

    store.selectedTask = { ...task, status: 'completed' }
    await store.archiveSelected()
    expect(apiMock.archiveTask).toHaveBeenCalledWith('task-1')
    expect(store.selectedTask).toBeNull()
    expect(store.selectedTaskId).toBe('')

    store.selectedTask = { ...task, status: 'failed' }
    apiMock.archiveTask.mockRejectedValueOnce(new Error('归档失败'))
    await store.archiveSelected()
    expect(store.error).toBe('归档失败')
    expect(store.actionPending).toBe('')
  })

  it('rejects malformed snapshots and reconnects after a closed stream', async () => {
    vi.useFakeTimers()
    class FakeEventSource {
      static instances: FakeEventSource[] = []
      listeners = new Map<string, (event: MessageEvent) => void>()
      onerror: (() => void) | null = null
      closed = false

      constructor(public url: string) {
        FakeEventSource.instances.push(this)
      }

      addEventListener(type: string, listener: (event: MessageEvent) => void): void {
        this.listeners.set(type, listener)
      }

      emitRaw(type: string, data: string): void {
        this.listeners.get(type)?.(new MessageEvent(type, { data }))
      }

      close(): void {
        this.closed = true
      }
    }
    vi.stubGlobal('EventSource', FakeEventSource)
    const store = useAgentTaskCenterStore()
    store.start()
    store.start()

    expect(FakeEventSource.instances).toHaveLength(1)
    await store.openTask('task-1')
    FakeEventSource.instances[0].emitRaw('task.snapshot', JSON.stringify([task]))
    expect(apiMock.getTask).toHaveBeenCalled()
    FakeEventSource.instances[0].emitRaw('task.snapshot', '{invalid')
    expect(store.error).toBe('任务快照格式无效')

    FakeEventSource.instances[0].emitRaw('stream.closed', '{}')
    FakeEventSource.instances[0].emitRaw('stream.closed', '{}')
    expect(store.connected).toBe(false)
    await vi.advanceTimersByTimeAsync(1500)
    expect(FakeEventSource.instances).toHaveLength(2)

    FakeEventSource.instances[1].onerror?.()
    await vi.advanceTimersByTimeAsync(1500)
    expect(FakeEventSource.instances).toHaveLength(3)
    store.stop()
    vi.useRealTimers()
  })
})

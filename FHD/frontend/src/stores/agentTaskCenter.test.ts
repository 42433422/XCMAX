vi.mock('@/utils/authenticatedEventStream', () => ({
  AuthenticatedEventStream: class {
    constructor(url: string) {
      return new EventSource(url)
    }
  },
}))
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
  markTaskRead: vi.fn(),
  taskEventStreamPath: vi.fn(() => '/api/agent/tasks/events/stream'),
}))

vi.mock('@/api/agentRuns', () => ({ default: apiMock }))
vi.mock('@/api/core', () => ({ buildFullApiUrl: (path: string) => path }))

import { useAgentTaskCenterStore } from './agentTaskCenter'
import type { AgentTaskProgress } from '@/api/agentRuns'

const task = {
  task_id: 'task-1',
  user_id: 'owner',
  title: '并发库存核对',
  source: 'agent',
  task_type: 'agent',
  status: 'waiting_user',
  attempt: 1,
  run_count: 1,
  active_run_id: 'run-1',
  capabilities: {
    approve: true,
    pause: true,
    cancel: true,
    retry: false,
    resume: false,
    evidence: true,
  },
  active_run: { run_id: 'run-1', user_id: 'owner', message: '核对库存', status: 'waiting_user' },
}

const fileProgress: AgentTaskProgress = {
  basis: 'files',
  percent: 62,
  completed_units: 13,
  settled_units: 13,
  total_units: 21,
  current_unit: 14,
  stage: '结果待核对',
  detail: '13/21 份已完成 · 已确认写入 141 行',
  status: 'blocked',
  attempt: 1,
  indeterminate: false,
  updated_at: '2026-11-19T12:00:00Z',
}
const stepProgress: AgentTaskProgress = { ...fileProgress, basis: 'steps', percent: 99, stage: '已阻断' }

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
    apiMock.getRun.mockResolvedValue({
      success: true,
      data: task.active_run,
      approval: { grant: 'grant-1' },
    })
    apiMock.continueRun.mockResolvedValue({
      success: true,
      data: { ...task.active_run, status: 'queued' },
    })
    apiMock.pauseRun.mockResolvedValue({ success: true, data: task.active_run })
    apiMock.cancelRun.mockResolvedValue({ success: true, data: task.active_run })
    apiMock.resumeRun.mockResolvedValue({ success: true, data: task.active_run })
    apiMock.retryRun.mockResolvedValue({ success: true, data: task.active_run })
    apiMock.archiveTask.mockResolvedValue({ success: true, data: task })
    apiMock.markTaskRead.mockResolvedValue({
      success: true,
      data: { ...task, attention_state: '', unread_count: 0 },
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('retains existing tasks when the server returns an unsuccessful envelope', async () => {
    const store = useAgentTaskCenterStore()
    await store.refresh()
    apiMock.listTasks.mockResolvedValueOnce({ success: false, data: [] })
    await store.refresh()
    expect(store.tasks).toHaveLength(1)
    expect(store.error).toContain('任务状态读取失败')
    await store.refresh()
    expect(store.error).toBe('')
  })

  it('loads independent task state and approves through the durable run contract', async () => {
    const store = useAgentTaskCenterStore()
    await store.refresh()

    expect(store.tasks).toHaveLength(1)
    expect(store.attentionCount).toBe(1)
    expect(store.approvalCount).toBe(1)
    expect(store.unreadCount).toBe(0)
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
    expect(apiMock.getTask).toHaveBeenCalledTimes(4)
  })

  it('preserves verified file progress across coarse snapshots for the same run only', async () => {
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
    apiMock.listTasks.mockResolvedValueOnce({ success: true, data: [{ ...task, progress: fileProgress }] })

    store.start()
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    await vi.waitFor(() => expect(store.tasks[0]?.progress).toEqual(fileProgress))
    const connection = FakeEventSource.instances[0]
    connection.emit('task.snapshot', [{ ...task, status: 'blocked', progress: stepProgress }])
    expect(store.tasks[0]).toMatchObject({ status: 'blocked', progress: fileProgress })

    const laterProgress = { ...fileProgress, percent: 67, updated_at: '2026-11-19T12:00:01Z' }
    connection.emit('task.snapshot', [{ ...task, status: 'blocked', progress: laterProgress }])
    connection.emit('task.snapshot', [{ ...task, status: 'blocked', progress: fileProgress }])
    expect(store.tasks[0].progress).toEqual(laterProgress)

    connection.emit('task.snapshot', [
      { ...task, active_run_id: 'run-2', status: 'completed', attention_state: 'result_unread', progress: stepProgress },
    ])

    expect(connection.url).toBe('/api/agent/tasks/events/stream')
    expect(store.connected).toBe(true)
    expect(store.tasks[0].status).toBe('completed')
    expect(store.tasks[0].progress).toEqual(stepProgress)
    expect(store.attentionCount).toBe(0)
    expect(store.approvalCount).toBe(0)
    expect(store.unreadCount).toBe(1)
    store.stop()
    expect(FakeEventSource.instances[0].closed).toBe(true)
  })

  it('drops the previous tenant snapshot and reconnects after a scope change', async () => {
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

      close(): void {
        this.closed = true
      }
    }
    vi.stubGlobal('EventSource', FakeEventSource)
    const store = useAgentTaskCenterStore()
    store.start()
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    await vi.waitFor(() => expect(store.tasks).toHaveLength(1))
    expect(store.tasks).toHaveLength(1)
    const priorRefreshCount = apiMock.listTasks.mock.calls.length

    apiMock.listTasks.mockResolvedValueOnce({ success: true, data: [] })
    store.restartForScope()

    expect(FakeEventSource.instances[0].closed).toBe(true)
    expect(store.tasks).toEqual([])
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(2))
    await vi.waitFor(() => expect(apiMock.listTasks).toHaveBeenCalledTimes(priorRefreshCount + 1))
    store.stop()
  })

  it('persists result read state and updates the workspace list snapshot', async () => {
    const store = useAgentTaskCenterStore()
    apiMock.listTasks.mockResolvedValueOnce({
      success: true,
      data: [{ ...task, status: 'completed', attention_state: 'result_unread', unread_count: 1, progress: fileProgress }],
    })
    apiMock.markTaskRead.mockResolvedValueOnce({
      success: true,
      data: { ...task, attention_state: '', unread_count: 0, progress: stepProgress },
    })
    await store.refresh()
    await store.openTask('task-1')
    expect(store.unreadCount).toBe(1)

    await store.markTaskRead('task-1')

    expect(apiMock.markTaskRead).toHaveBeenCalledWith('task-1')
    expect(store.tasks[0].attention_state).toBe('')
    expect(store.tasks[0].progress).toEqual(fileProgress)
    expect(store.selectedTask?.progress).toEqual(fileProgress)
    expect(store.unreadCount).toBe(0)
  })

  it('stops the workspace after an unauthorized list or stream and stays stopped', async () => {
    class FakeEventSource {
      static instances: FakeEventSource[] = []
      listeners = new Map<string, () => void>()
      onerror: (() => void) | null = null
      closed = false
      constructor(public url: string) {
        FakeEventSource.instances.push(this)
      }
      addEventListener(type: string, listener: () => void): void {
        this.listeners.set(type, listener)
      }
      emit(type: string): void {
        this.listeners.get(type)?.()
      }
      close(): void {
        this.closed = true
      }
    }
    vi.stubGlobal('EventSource', FakeEventSource)
    const store = useAgentTaskCenterStore()
    apiMock.listTasks.mockRejectedValueOnce(Object.assign(new Error('unauthorized'), { status: 401 }))
    await store.refresh()
    expect(store.tasks).toEqual([])
    expect(store.error).toBe('')
    apiMock.listTasks.mockRejectedValueOnce(Object.assign(new Error('unauthorized'), { status: 403 }))
    await store.refresh()
    expect(apiMock.listTasks).toHaveBeenCalledTimes(2)

    store.resumeAfterLogin()
    await vi.waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0))
    const stream = FakeEventSource.instances.at(-1)!
    stream.emit('stream.unauthorized')
    stream.emit('stream.unauthorized')
    expect(stream.closed).toBe(true)
    expect(store.tasks).toEqual([])
    store.start()
    expect(FakeEventSource.instances.at(-1)).toBe(stream)
    store.resumeAfterLogin()
    store.stop()
  })

  it('handles refresh and detail failures without losing durable state', async () => {
    const store = useAgentTaskCenterStore()
    apiMock.listTasks.mockRejectedValueOnce(new Error('任务加载失败'))
    await store.refresh()
    expect(store.error).toBe('任务加载失败')
    expect(store.loading).toBe(false)

    await store.refreshDetail()
    expect(apiMock.getTask).not.toHaveBeenCalled()
    store.selectedTaskId = 'missing-task'
    apiMock.getTask.mockRejectedValueOnce('offline')
    await store.refreshDetail()
    expect(store.error).toBe('工作区列表暂时不可用')
  })

  it('reports malformed payloads without clearing the current selection', async () => {
    const store = useAgentTaskCenterStore()
    store.selectedTaskId = 'stale-task'
    store.selectedTask = null
    apiMock.listTasks.mockResolvedValueOnce({ success: true, data: { invalid: true } })
    apiMock.getTaskRuntime.mockResolvedValueOnce({ success: true })
    await store.refresh()

    expect(store.tasks).toEqual([])
    expect(store.selectedTaskId).toBe('stale-task')
    expect(store.error).toContain('任务状态读取失败')
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
    store.selectedTask = {
      ...task,
      active_run_id: undefined,
      active_run: undefined,
      runs: undefined,
    }
    apiMock.getTask.mockResolvedValueOnce({ success: true, data: store.selectedTask })
    await store.control('pause')
    expect(apiMock.pauseRun).not.toHaveBeenCalled()
    expect(store.error).toBe('工作区当前没有可控制的运行')
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

  it('controls a routed workspace from a freshly loaded canonical task detail', async () => {
    const store = useAgentTaskCenterStore()

    await store.controlTask('task-1', 'pause')

    expect(apiMock.getTask).toHaveBeenCalledWith('task-1')
    expect(apiMock.pauseRun).toHaveBeenCalledWith('run-1')
    expect(apiMock.listTasks).toHaveBeenCalledOnce()
    expect(store.actionPending).toBe('')

    apiMock.getTask.mockResolvedValueOnce({ success: true })
    await store.controlTask('missing-task', 'cancel')
    expect(store.error).toContain('工作区任务不存在')
    expect(apiMock.cancelRun).not.toHaveBeenCalled()
  })

  it('fails closed when approval has no grant and ignores missing runs', async () => {
    const store = useAgentTaskCenterStore()
    store.selectedTask = { ...task, active_run_id: undefined, active_run: undefined, runs: [] }
    apiMock.getTask.mockResolvedValueOnce({ success: true, data: store.selectedTask })
    await store.control('pause')
    expect(apiMock.pauseRun).not.toHaveBeenCalled()
    expect(store.error).toBe('工作区当前没有可控制的运行')

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

it.each(['scope', 'selection'])('discards detail response after %s changes', async (change) => {
  setActivePinia(createPinia())
  let resolve!: (value: unknown) => void
  apiMock.getTask.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r
    }),
  )
  const store = useAgentTaskCenterStore()
  const pending = store.openTask('old-task')
  if (change === 'scope') store.restartForScope()
  else store.showTaskList()
  resolve({ success: true, data: { ...task, task_id: 'old-task' } })
  await pending
  expect(store.selectedTask).toBeNull()
  expect(store.selectedTaskId).toBe('')
})

it('does not submit an approval fetched before a scope switch', async () => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  apiMock.getTask.mockResolvedValue({ success: true, data: task })
  let resolve!: (value: unknown) => void
  apiMock.getRun.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r
    }),
  )
  const store = useAgentTaskCenterStore()
  await store.openTask('task-1')
  const pending = store.control('approve')
  store.restartForScope()
  resolve({ success: true, approval: { grant: 'old-grant' } })
  await pending
  expect(apiMock.continueRun).not.toHaveBeenCalled()
  expect(store.actionPending).toBe('')
})

it.each(['scope', 'run'])('does not apply an old read receipt after the %s changes', async (change) => {
  setActivePinia(createPinia())
  let resolve!: (value: unknown) => void
  apiMock.markTaskRead.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r
    }),
  )
  const store = useAgentTaskCenterStore()
  const pending = store.markTaskRead('task-1')
  if (change === 'scope') store.restartForScope()
  store.tasks = [
    { ...task, ...(change === 'run' ? { active_run_id: 'run-2' } : {}), title: 'new snapshot', attention_state: 'result_unread' },
  ]
  resolve({ success: true, data: { ...task, title: 'old scope', attention_state: '' } })
  await pending
  expect(store.tasks[0].title).toBe('new snapshot')
  expect(store.tasks[0].attention_state).toBe('result_unread')
})

describe('shared office stream consistency', () => {
  class Stream {
    static current: Stream
    listeners = new Map<string, (event: MessageEvent) => void>()
    onerror: (() => void) | null = null
    constructor() {
      Stream.current = this
    }
    addEventListener(type: string, listener: (event: MessageEvent) => void) {
      this.listeners.set(type, listener)
    }
    emit(value: unknown) {
      this.listeners.get('task.snapshot')?.(new MessageEvent('task.snapshot', { data: JSON.stringify(value) }))
    }
    close() {}
  }
  let store: ReturnType<typeof useAgentTaskCenterStore>
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    vi.stubGlobal('EventSource', Stream)
    apiMock.listTasks.mockResolvedValue({ success: true, data: [task] })
    apiMock.getTaskRuntime.mockResolvedValue({ success: true, data: { running: true, max_workers: 4, active_count: 1 } })
    apiMock.getTask.mockResolvedValue({ success: true, data: task })
    store = useAgentTaskCenterStore()
  })
  afterEach(() => {
    store.stop()
    vi.unstubAllGlobals()
  })

  it('does not let slow HTTP erase newer stream tasks or regress a later attempt', async () => {
    let resolve!: (value: unknown) => void
    apiMock.listTasks.mockReturnValueOnce(
      new Promise((r) => {
        resolve = r
      }),
    )
    store.start()
    const done = { ...task, status: 'completed', updated_at: '2026-11-22T01:00:02Z', metadata: { employee_id: 'worker' } }
    Stream.current.emit([done, { ...done, task_id: 'new-task' }])
    resolve({ success: true, data: [{ ...task, updated_at: '2026-11-22T01:00:00Z' }] })
    await vi.waitFor(() => expect(store.loading).toBe(false))
    expect(store.tasks.map((row) => [row.task_id, row.status])).toEqual([
      ['task-1', 'completed'],
      ['new-task', 'completed'],
    ])
    Stream.current.emit([{ ...done, active_run_id: 'run-2', attempt: 2, status: 'running' }])
    Stream.current.emit([done])
    expect(store.tasks[0]).toMatchObject({ attempt: 2, active_run_id: 'run-2', status: 'running' })
  })

  it('retains explicit worker identity through old lightweight snapshots and marks disconnect stale', async () => {
    apiMock.listTasks.mockResolvedValueOnce({
      success: true,
      data: [{ ...task, active_run: { ...task.active_run, steps: [{ tool_id: 'employee', params: { employee_id: 'printer' } }] } }],
    })
    store.start()
    await vi.waitFor(() => expect(store.loading).toBe(false))
    Stream.current.emit([{ ...task, active_run: null, runs: [] }])
    expect(store.tasks[0].metadata?.employee_id).toBe('printer')
    expect(store.stale).toBe(false)
    expect(store.lastVerifiedAt).toBeGreaterThan(0)
    Stream.current.onerror?.()
    expect(store.stale).toBe(true)
    expect(store.tasks).toHaveLength(1)
  })

  it('rejects a structurally invalid snapshot without clearing known tasks', async () => {
    store.start()
    await vi.waitFor(() => expect(store.loading).toBe(false))
    Stream.current.emit({ tasks: [] })
    expect(store.tasks).toHaveLength(1)
    expect(store.stale).toBe(true)
    Stream.current.emit([task])
    expect(store.stale).toBe(false)
  })

  it('checks failed control envelopes and performs a new read after an in-flight pre-action read', async () => {
    apiMock.pauseRun.mockResolvedValueOnce({ success: false, message: '暂停被拒绝' })
    await store.controlTask('task-1', 'pause')
    expect(store.error).toBe('暂停被拒绝')
    expect(apiMock.listTasks).not.toHaveBeenCalled()
    let resolve!: (value: unknown) => void
    apiMock.listTasks
      .mockReturnValueOnce(
        new Promise((r) => {
          resolve = r
        }),
      )
      .mockResolvedValueOnce({ success: true, data: [{ ...task, status: 'paused' }] })
    apiMock.pauseRun.mockResolvedValueOnce({ success: true, data: task.active_run })
    const beforeAction = store.refresh()
    const action = store.controlTask('task-1', 'pause')
    await vi.waitFor(() => expect(apiMock.pauseRun).toHaveBeenCalledTimes(2))
    resolve({ success: true, data: [task] })
    await Promise.all([beforeAction, action])
    expect(apiMock.listTasks).toHaveBeenCalledTimes(2)
    expect(store.tasks[0].status).toBe('paused')
    expect(store.stale).toBe(false)
  })

  it('does not treat command acknowledgement as a completed state transition', async () => {
    apiMock.getTask.mockResolvedValue({ success: true, data: { ...task, status: 'running' } })
    apiMock.listTasks.mockResolvedValue({ success: true, data: [{ ...task, status: 'running' }] })
    apiMock.pauseRun.mockResolvedValueOnce({ success: true, data: { ...task.active_run, status: 'paused' } })
    await store.controlTask('task-1', 'pause')
    expect(store.tasks[0].status).toBe('running')
    apiMock.getTask.mockResolvedValueOnce({ success: false, message: '状态读取失败' })
    await store.controlTask('task-1', 'pause')
    expect(apiMock.pauseRun).toHaveBeenCalledOnce()
    expect(store.stale).toBe(true)
  })

  it('discards responses from the first visit after an A to B to A account switch', async () => {
    let resolve!: (value: unknown) => void
    apiMock.listTasks.mockReturnValueOnce(
      new Promise((r) => {
        resolve = r
      }),
    )
    const oldRequest = store.refresh()
    store.restartForScope()
    store.restartForScope()
    apiMock.listTasks.mockResolvedValueOnce({ success: true, data: [] })
    await store.refresh()
    resolve({ success: true, data: [{ ...task, title: 'first A session' }] })
    await oldRequest
    expect(store.tasks).toEqual([])
    expect(store.stale).toBe(false)
  })

  it('does not downgrade a valid stream snapshot after an older HTTP request fails', async () => {
    let reject!: (error: unknown) => void
    apiMock.listTasks.mockReturnValueOnce(
      new Promise((_resolve, r) => {
        reject = r
      }),
    )
    store.start()
    Stream.current.emit([task])
    reject(new Error('old request timeout'))
    await vi.waitFor(() => expect(store.loading).toBe(false))
    expect(store.stale).toBe(false)
    expect(store.error).toBe('')
  })
})

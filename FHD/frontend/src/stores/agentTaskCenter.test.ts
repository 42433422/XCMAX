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
})

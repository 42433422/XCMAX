import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick, reactive, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { formatWorkDurationShort, totalWorkMs, useNowMsTicker, useWorkflowEmployeeDesks } from './useWorkflowEmployeeDesks'
import type { WorkflowEmployeeSession, WorkflowEmployeeSpaceSnapshot } from '@/stores/workflowEmployeeSpace'

// Mock pinia 的 storeToRefs，使其直接返回 store（保留响应性）
vi.mock('pinia', async () => {
  const actual = await vi.importActual<typeof import('pinia')>('pinia')
  return {
    ...actual,
    storeToRefs: (store: any) => store,
  }
})

// 使用真实 ref 以保证 computed 响应性
const registryEntriesRef = ref<Array<{ id: string; label: string; hostModId?: string; carrierModId?: string }>>([])
const workflowEnabledRef = ref<Record<string, boolean>>({})
const snapshotsRef = ref<Record<string, WorkflowEmployeeSpaceSnapshot>>({})
const sessionsRef = ref<Record<string, WorkflowEmployeeSession>>({})
const taskCenter = reactive({ tasks: [] as any[], connected: true, stale: false, lastVerifiedAt: 100, error: '', start: vi.fn() })
vi.mock('@/stores/agentTaskCenter', () => ({ useAgentTaskCenterStore: () => taskCenter }))

// Mock workflowAiEmployees store
vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: () => ({
    enabled: workflowEnabledRef,
    registryEntries: registryEntriesRef,
  }),
}))

// Mock workflowEmployeeSpace store
vi.mock('@/stores/workflowEmployeeSpace', () => ({
  useWorkflowEmployeeSpaceStore: () => ({
    snapshots: snapshotsRef,
    sessions: sessionsRef,
  }),
}))

// Mock workflowEmployeeDisplayName
vi.mock('@/utils/workflowEmployeeDisplayName', () => ({
  shortNameFromPanelTitle: (raw: string) => {
    let s = String(raw || '').trim()
    if (!s) return '员工'
    s = s.replace(/^工作流\s*[·•]\s*/i, '')
    s = s.replace(/\s*AI\s*员工\s*$/i, '')
    s = s.replace(/\s+/g, ' ').trim()
    return s || '员工'
  },
}))

function resetMocks() {
  registryEntriesRef.value = []
  workflowEnabledRef.value = {}
  snapshotsRef.value = {}
  sessionsRef.value = {}
  Object.assign(taskCenter, { tasks: [], connected: true, stale: false, lastVerifiedAt: 100, error: '' })
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  resetMocks()
})

describe('duration formatting and accumulated work', () => {
  it.each([
    ...[NaN, Infinity, -Infinity, -1, -1000, 0].map((input) => [input, '0m']),
    [1, '0s'],
    [999, '0s'],
    [1000, '1s'],
    [59000, '59s'],
    [60000, '1m'],
    [3540000, '59m'],
    [3600000, '1h'],
    [7200000, '2h'],
    [9000000, '2h 30m'],
    [86400000, '1d'],
    [172800000, '2d'],
    [126000000, '1d 11h'],
  ])('formats %s milliseconds as %s', (input, expected) => {
    expect(formatWorkDurationShort(input as number)).toBe(expected)
  })
  it.each([
    [undefined, 0],
    [null, 0],
    [{ lifetimeMs: 5000, enabledAt: null }, 5000],
    [{ lifetimeMs: 5000, enabledAt: 10000 }, 15000],
    [{ lifetimeMs: 5000, enabledAt: 30000 }, 5000],
    [{ lifetimeMs: -100, enabledAt: null }, 0],
    [{ lifetimeMs: 0, enabledAt: null }, 0],
    [{ lifetimeMs: 0, enabledAt: 15000 }, 5000],
  ])('accumulates session %j as %s milliseconds', (session, expected) => {
    expect(totalWorkMs(session as WorkflowEmployeeSession, 20000)).toBe(expected)
  })
})

describe('useNowMsTicker', () => {
  it('在组件挂载时初始化 nowMs', async () => {
    const before = Date.now()
    let capturedNowMs: any = null

    const TestComp = defineComponent({
      setup() {
        const nowMs = useNowMsTicker(60000)
        capturedNowMs = nowMs
        return () => h('div')
      },
    })

    mount(TestComp)
    await nextTick()

    expect(capturedNowMs).toBeTruthy()
    expect(capturedNowMs.value).toBeGreaterThanOrEqual(before)
  })

  it('使用默认 interval 30000ms', async () => {
    const setIntervalSpy = vi.spyOn(window, 'setInterval').mockReturnValue(1 as any)
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval').mockImplementation(() => {})

    const TestComp = defineComponent({
      setup() {
        useNowMsTicker()
        return () => h('div')
      },
    })

    const wrapper = mount(TestComp)
    await nextTick()

    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 30000)

    wrapper.unmount()
    setIntervalSpy.mockRestore()
    clearIntervalSpy.mockRestore()
  })

  it('interval 小于 1000ms 时被 clamp 到 1000ms', async () => {
    const setIntervalSpy = vi.spyOn(window, 'setInterval').mockReturnValue(1 as any)
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval').mockImplementation(() => {})

    const TestComp = defineComponent({
      setup() {
        useNowMsTicker(500)
        return () => h('div')
      },
    })

    const wrapper = mount(TestComp)
    await nextTick()

    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 1000)

    wrapper.unmount()
    setIntervalSpy.mockRestore()
    clearIntervalSpy.mockRestore()
  })

  it('自定义 interval 大于 1000ms 时按原值使用', async () => {
    const setIntervalSpy = vi.spyOn(window, 'setInterval').mockReturnValue(1 as any)
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval').mockImplementation(() => {})

    const TestComp = defineComponent({
      setup() {
        useNowMsTicker(5000)
        return () => h('div')
      },
    })

    const wrapper = mount(TestComp)
    await nextTick()

    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 5000)

    wrapper.unmount()
    setIntervalSpy.mockRestore()
    clearIntervalSpy.mockRestore()
  })

  it('组件卸载时清理定时器', async () => {
    const fakeTimerId = 12345
    const setIntervalSpy = vi.spyOn(window, 'setInterval').mockReturnValue(fakeTimerId as any)
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval').mockImplementation(() => {})

    const TestComp = defineComponent({
      setup() {
        useNowMsTicker(60000)
        return () => h('div')
      },
    })

    const wrapper = mount(TestComp)
    await nextTick()

    wrapper.unmount()

    expect(clearIntervalSpy).toHaveBeenCalledWith(fakeTimerId)

    setIntervalSpy.mockRestore()
    clearIntervalSpy.mockRestore()
  })

  it('定时器触发时更新 nowMs', async () => {
    vi.useFakeTimers()
    const setIntervalSpy = vi.spyOn(window, 'setInterval').mockReturnValue(1 as any)
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval').mockImplementation(() => {})

    let capturedNowMs: any = null
    const TestComp = defineComponent({
      setup() {
        const nowMs = useNowMsTicker(1000)
        capturedNowMs = nowMs
        return () => h('div')
      },
    })

    const wrapper = mount(TestComp)
    await nextTick()

    const initialValue = capturedNowMs.value
    vi.advanceTimersByTime(1500)
    await nextTick()

    expect(capturedNowMs.value).toBeGreaterThanOrEqual(initialValue)

    wrapper.unmount()
    vi.useRealTimers()
    setIntervalSpy.mockRestore()
    clearIntervalSpy.mockRestore()
  })
})

describe('useWorkflowEmployeeDesks shared task projection', () => {
  function setupComposable() {
    let captured!: ReturnType<typeof useWorkflowEmployeeDesks>
    const wrapper = mount(
      defineComponent({
        setup() {
          captured = useWorkflowEmployeeDesks()
          return () => h('div')
        },
      }),
    )
    return { captured, wrapper }
  }
  const running = {
    task_id: 'task-1',
    active_run_id: 'run-1',
    status: 'running',
    title: '打印发货标签',
    metadata: { employee_id: 'emp1' },
    updated_at: '2026-11-22T01:00:00Z',
  }

  it('retains registry identity, entitlement carriers and management preference', () => {
    registryEntriesRef.value = [
      { id: 'emp1', label: '员工1', hostModId: 'host', carrierModId: 'carrier' },
      { id: 'emp2', label: '员工2' },
    ]
    workflowEnabledRef.value = { emp1: true }
    const { captured, wrapper } = setupComposable()
    expect(captured.employeeIds.value).toEqual(['emp1', 'emp2'])
    expect(captured.desks.value[0]).toMatchObject({
      empId: 'emp1',
      shortName: '员工1',
      hostModId: 'host',
      carrierModId: 'carrier',
      enabled: true,
    })
    expect(captured.onDutyDesks.value.map((row) => row.empId)).toEqual(['emp1'])
    expect(taskCenter.start).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('projects the same task transitions into every mounted view without consulting the activity cache', () => {
    registryEntriesRef.value = [{ id: 'emp1', label: '员工1' }]
    taskCenter.tasks = [running]
    snapshotsRef.value.emp1 = { shortName: '旧缓存', visuallyBusy: false } as WorkflowEmployeeSpaceSnapshot
    const first = setupComposable(),
      second = setupComposable()
    expect(first.captured.desks.value[0].taskId).toBe('task-1')
    // A local enable toggle cannot hide a task that is actually executing.
    expect(first.captured.isBusy(first.captured.desks.value[0])).toBe(true)
    taskCenter.tasks = [{ ...running, status: 'waiting_user' }]
    expect(first.captured.desks.value[0].snapshot?.officeState).toBe('waiting')
    expect(second.captured.statusLine(second.captured.desks.value[0])).toBe('等待审批')
    taskCenter.stale = true
    expect(first.captured.isBusy(first.captured.desks.value[0])).toBe(false)
    expect(second.captured.desks.value[0].snapshot?.officeState).toBe('offline')
    taskCenter.tasks = [] // GlobalTaskCenter clears this on an authenticated scope change.
    expect(first.captured.desks.value[0].tasks).toEqual([])
    expect(second.captured.desks.value[0].taskId).toBeUndefined()
    first.wrapper.unmount()
    second.wrapper.unmount()
  })

  it('counts completed visible server tasks once and excludes phase updates and old cumulative counters', () => {
    registryEntriesRef.value = [{ id: 'emp1', label: '员工1' }]
    sessionsRef.value.emp1 = { processedCount: 99 } as WorkflowEmployeeSession
    taskCenter.tasks = [running, { ...running, task_id: 'done-1', status: 'completed' }]
    const { captured, wrapper } = setupComposable()
    const count = () => captured.processedCount(captured.desks.value[0])
    expect(count()).toBe(1)
    taskCenter.tasks = [running, { ...running, task_id: 'done-1', status: 'completed' }]
    expect(count()).toBe(1)
    expect(captured.desks.value[0].session?.processedCount).toBe(99)
    wrapper.unmount()
  })
})

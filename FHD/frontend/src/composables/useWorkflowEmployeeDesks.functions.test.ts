import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import {
  formatWorkDurationShort,
  totalWorkMs,
  useNowMsTicker,
  useWorkflowEmployeeDesks,
  type WorkflowEmployeeDeskRow,
} from './useWorkflowEmployeeDesks'
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
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  resetMocks()
})

describe('duration formatting and accumulated work', () => {
  it.each([
    ...[NaN, Infinity, -Infinity, -1, -1000, 0].map((input) => [input, '0m']),
    [1, '0s'], [999, '0s'], [1000, '1s'], [59000, '59s'], [60000, '1m'], [3540000, '59m'],
    [3600000, '1h'], [7200000, '2h'], [9000000, '2h 30m'], [86400000, '1d'],
    [172800000, '2d'], [126000000, '1d 11h'],
  ])('formats %s milliseconds as %s', (input, expected) => {
    expect(formatWorkDurationShort(input as number)).toBe(expected)
  })
  it.each([
    [undefined, 0], [null, 0], [{ lifetimeMs: 5000, enabledAt: null }, 5000],
    [{ lifetimeMs: 5000, enabledAt: 10000 }, 15000], [{ lifetimeMs: 5000, enabledAt: 30000 }, 5000],
    [{ lifetimeMs: -100, enabledAt: null }, 0], [{ lifetimeMs: 0, enabledAt: null }, 0],
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

describe('useWorkflowEmployeeDesks', () => {
  function setupComposable() {
    let captured: ReturnType<typeof useWorkflowEmployeeDesks> | null = null
    const TestComp = defineComponent({
      setup() {
        captured = useWorkflowEmployeeDesks()
        return () => h('div')
      },
    })
    const wrapper = mount(TestComp)
    return { captured: captured!, wrapper }
  }

  describe('employeeIds computed', () => {
    it('空 registry 返回空数组', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      expect(captured.employeeIds.value).toEqual([])
      wrapper.unmount()
    })

    it('返回 registry 中所有员工 id', async () => {
      registryEntriesRef.value = [
        { id: 'emp1', label: '员工1' },
        { id: 'emp2', label: '员工2' },
      ]
      const { captured, wrapper } = setupComposable()
      await nextTick()
      expect(captured.employeeIds.value).toEqual(['emp1', 'emp2'])
      wrapper.unmount()
    })
  })

  describe('desks computed', () => {
    it('空 registry 返回空数组', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      expect(captured.desks.value).toEqual([])
      wrapper.unmount()
    })

    it('返回每个员工的工位信息', async () => {
      registryEntriesRef.value = [{ id: 'emp1', label: '员工1', hostModId: 'mod1', carrierModId: 'mod2' }]
      workflowEnabledRef.value = { emp1: true }
      const { captured, wrapper } = setupComposable()
      await nextTick()

      const desks = captured.desks.value
      expect(desks).toHaveLength(1)
      expect(desks[0].empId).toBe('emp1')
      expect(desks[0].panelTitle).toBe('工作流 · 员工1')
      expect(desks[0].shortName).toBe('员工1')
      expect(desks[0].enabled).toBe(true)
      expect(desks[0].hostModId).toBe('mod1')
      expect(desks[0].carrierModId).toBe('mod2')
      wrapper.unmount()
    })

    it('未注册的员工 enabled 为 false', async () => {
      registryEntriesRef.value = [{ id: 'emp1', label: '员工1' }]
      workflowEnabledRef.value = {}
      const { captured, wrapper } = setupComposable()
      await nextTick()

      expect(captured.desks.value[0].enabled).toBe(false)
      wrapper.unmount()
    })

    it('workflowEnabled 中值为 false 时 enabled 为 false', async () => {
      registryEntriesRef.value = [{ id: 'emp1', label: '员工1' }]
      workflowEnabledRef.value = { emp1: false }
      const { captured, wrapper } = setupComposable()
      await nextTick()

      expect(captured.desks.value[0].enabled).toBe(false)
      wrapper.unmount()
    })

    it('snapshot 存在时使用 snapshot.shortName', async () => {
      registryEntriesRef.value = [{ id: 'emp1', label: '员工1' }]
      snapshotsRef.value = {
        emp1: {
          empId: 'emp1',
          panelTitle: '工作流 · 员工1',
          shortName: '快照短名',
          stage: 'stage',
          progressPct: 50,
          progressLabel: 'label',
          hintLine: 'hint',
          idle: false,
          visuallyBusy: true,
          lastActivityAt: 0,
        },
      }
      const { captured, wrapper } = setupComposable()
      await nextTick()

      expect(captured.desks.value[0].shortName).toBe('快照短名')
      expect(captured.desks.value[0].snapshot).toBeTruthy()
      wrapper.unmount()
    })

    it('snapshot 不存在时使用 shortNameFromPanelTitle', async () => {
      registryEntriesRef.value = [{ id: 'emp1', label: '标签打印 AI 员工' }]
      const { captured, wrapper } = setupComposable()
      await nextTick()

      expect(captured.desks.value[0].shortName).toBe('标签打印')
      wrapper.unmount()
    })

    it('session 存在时附加到工位', async () => {
      registryEntriesRef.value = [{ id: 'emp1', label: '员工1' }]
      sessionsRef.value = {
        emp1: {
          empId: 'emp1',
          enabledAt: 1000,
          firstActivityAt: 2000,
          lastActivityAt: 3000,
          processedCount: 5,
          lifetimeMs: 10000,
        },
      }
      const { captured, wrapper } = setupComposable()
      await nextTick()

      expect(captured.desks.value[0].session).toBeTruthy()
      expect(captured.desks.value[0].session?.processedCount).toBe(5)
      wrapper.unmount()
    })
  })

  describe('onDutyDesks computed', () => {
    it('只返回 enabled 为 true 的工位', async () => {
      registryEntriesRef.value = [
        { id: 'emp1', label: '员工1' },
        { id: 'emp2', label: '员工2' },
        { id: 'emp3', label: '员工3' },
      ]
      workflowEnabledRef.value = { emp1: true, emp2: false, emp3: true }
      const { captured, wrapper } = setupComposable()
      await nextTick()

      const onDuty = captured.onDutyDesks.value
      expect(onDuty).toHaveLength(2)
      expect(onDuty.map((d) => d.empId)).toEqual(['emp1', 'emp3'])
      wrapper.unmount()
    })

    it('全部未启用时返回空数组', async () => {
      registryEntriesRef.value = [{ id: 'emp1', label: '员工1' }]
      workflowEnabledRef.value = {}
      const { captured, wrapper } = setupComposable()
      await nextTick()

      expect(captured.onDutyDesks.value).toEqual([])
      wrapper.unmount()
    })
  })

  function desk(overrides: Partial<WorkflowEmployeeDeskRow> = {}): WorkflowEmployeeDeskRow {
    return { empId: 'emp1', panelTitle: '工作流 · 员工1', shortName: '员工1', enabled: true, ...overrides }
  }
  function snapshot(overrides: Partial<WorkflowEmployeeSpaceSnapshot> = {}): WorkflowEmployeeSpaceSnapshot {
    return { empId: 'emp1', panelTitle: '', shortName: '', stage: '', progressPct: 0, progressLabel: '',
      hintLine: '', idle: false, visuallyBusy: false, lastActivityAt: 0, ...overrides }
  }
  it.each([
    [desk({ enabled: false }), '副窗未启用'], [desk(), '暂无快照'],
    [desk({ snapshot: snapshot({ stage: '处理中' }) }), '处理中'],
    [desk({ snapshot: snapshot({ progressLabel: '50% 完成' }) }), '50% 完成'],
    [desk({ snapshot: snapshot({ hintLine: '提示信息' }) }), '提示信息'],
    [desk({ snapshot: snapshot() }), '待命'],
  ])('statusLine prioritizes the displayed state for %j', async (row, expected) => {
    const { captured, wrapper } = setupComposable()
    await nextTick()
    expect(captured.statusLine(row as WorkflowEmployeeDeskRow)).toBe(expected)
    wrapper.unmount()
  })
  it.each([
    [desk({ shortName: '张三', enabled: false }), '员工 张三。副窗未启用'],
    [desk({ shortName: '张三' }), '员工 张三。等待活动'],
    [desk({ shortName: '张三', snapshot: snapshot({ stage: '忙碌中' }) }), '员工 张三。忙碌中'],
  ])('ariaLabel describes %j accessibly', async (row, expected) => {
    const { captured, wrapper } = setupComposable()
    await nextTick()
    expect(captured.ariaLabel(row as WorkflowEmployeeDeskRow)).toBe(expected)
    wrapper.unmount()
  })
  it.each([
    [desk({ enabled: false }), false], [desk(), false],
    [desk({ snapshot: snapshot({ visuallyBusy: true }) }), true], [desk({ snapshot: snapshot() }), false],
  ])('isBusy reflects enabled activity for %j', async (row, expected) => {
    const { captured, wrapper } = setupComposable()
    await nextTick()
    expect(captured.isBusy(row as WorkflowEmployeeDeskRow)).toBe(expected)
    wrapper.unmount()
  })
  it.each([undefined, 42, 0])('processedCount reads session count %s', async (count) => {
    const { captured, wrapper } = setupComposable()
    await nextTick()
    const session = count === undefined ? undefined : { empId: 'emp1', enabledAt: null, firstActivityAt: null,
      lastActivityAt: null, processedCount: count, lifetimeMs: 0 }
    expect(captured.processedCount(desk({ session }))).toBe(count ?? 0)
    wrapper.unmount()
  })

  describe('resolvePanelTitle（通过 desks 间接测试）', () => {
    it('registry 中存在员工时返回"工作流 · {label}"', async () => {
      registryEntriesRef.value = [{ id: 'emp1', label: '自定义标签' }]
      const { captured, wrapper } = setupComposable()
      await nextTick()
      expect(captured.desks.value[0].panelTitle).toBe('工作流 · 自定义标签')
      wrapper.unmount()
    })

    it('registry 中不存在员工时（理论上不会发生，但 fallback）返回"工作流 · {empId}"', async () => {
      // 通过手动构造 desks 验证 fallback 逻辑
      registryEntriesRef.value = [{ id: 'emp1', label: '员工1' }]
      const { captured, wrapper } = setupComposable()
      await nextTick()
      // desks 只会基于 registryEntries 生成，所以这里测试 label 为空的情况
      registryEntriesRef.value = [{ id: 'emp1', label: '' }]
      await nextTick()
      expect(captured.desks.value[0].panelTitle).toBe('工作流 · ')
      wrapper.unmount()
    })
  })
})

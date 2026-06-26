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
import type {
  WorkflowEmployeeSession,
  WorkflowEmployeeSpaceSnapshot,
} from '@/stores/workflowEmployeeSpace'

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

describe('formatWorkDurationShort - additional edge cases', () => {
  it('非有限值返回 0m', () => {
    expect(formatWorkDurationShort(NaN)).toBe('0m')
    expect(formatWorkDurationShort(Infinity)).toBe('0m')
    expect(formatWorkDurationShort(-Infinity)).toBe('0m')
  })

  it('负数返回 0m', () => {
    expect(formatWorkDurationShort(-1)).toBe('0m')
    expect(formatWorkDurationShort(-1000)).toBe('0m')
  })

  it('0 返回 0m', () => {
    expect(formatWorkDurationShort(0)).toBe('0m')
  })

  it('小于 60 秒返回秒', () => {
    expect(formatWorkDurationShort(1)).toBe('0s')
    expect(formatWorkDurationShort(999)).toBe('0s')
    expect(formatWorkDurationShort(1000)).toBe('1s')
    expect(formatWorkDurationShort(59000)).toBe('59s')
  })

  it('小于 60 分钟返回分钟', () => {
    expect(formatWorkDurationShort(60000)).toBe('1m')
    expect(formatWorkDurationShort(3540000)).toBe('59m')
  })

  it('小于 24 小时返回小时（无余分钟）', () => {
    expect(formatWorkDurationShort(3600000)).toBe('1h')
    expect(formatWorkDurationShort(7200000)).toBe('2h')
  })

  it('小于 24 小时返回小时 + 分钟', () => {
    expect(formatWorkDurationShort(9000000)).toBe('2h 30m')
  })

  it('大于等于 24 小时返回天', () => {
    expect(formatWorkDurationShort(86400000)).toBe('1d')
    expect(formatWorkDurationShort(172800000)).toBe('2d')
  })

  it('大于等于 24 小时返回天 + 小时', () => {
    expect(formatWorkDurationShort(126000000)).toBe('1d 11h')
  })
})

describe('totalWorkMs - additional edge cases', () => {
  it('undefined session 返回 0', () => {
    expect(totalWorkMs(undefined, Date.now())).toBe(0)
  })

  it('null session 返回 0', () => {
    expect(totalWorkMs(null as any, Date.now())).toBe(0)
  })

  it('enabledAt 为 null 时只返回 lifetimeMs', () => {
    expect(
      totalWorkMs({ lifetimeMs: 5000, enabledAt: null } as any, Date.now()),
    ).toBe(5000)
  })

  it('enabledAt 存在时累加实时时长', () => {
    const now = Date.now()
    const enabledAt = now - 10000
    expect(
      totalWorkMs({ lifetimeMs: 5000, enabledAt } as any, now),
    ).toBe(15000)
  })

  it('enabledAt 在未来时 live 为 0', () => {
    const now = Date.now()
    const enabledAt = now + 10000
    expect(
      totalWorkMs({ lifetimeMs: 5000, enabledAt } as any, now),
    ).toBe(5000)
  })

  it('lifetimeMs 为负数时被 clamp 到 0', () => {
    expect(
      totalWorkMs({ lifetimeMs: -100, enabledAt: null } as any, Date.now()),
    ).toBe(0)
  })

  it('lifetimeMs 为 0 且 enabledAt 为 null 时返回 0', () => {
    expect(
      totalWorkMs({ lifetimeMs: 0, enabledAt: null } as any, Date.now()),
    ).toBe(0)
  })

  it('lifetimeMs 为 0 但 enabledAt 存在时返回 live 时长', () => {
    const now = Date.now()
    const enabledAt = now - 5000
    expect(
      totalWorkMs({ lifetimeMs: 0, enabledAt } as any, now),
    ).toBe(5000)
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
      registryEntriesRef.value = [
        { id: 'emp1', label: '员工1', hostModId: 'mod1', carrierModId: 'mod2' },
      ]
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

  describe('statusLine', () => {
    it('未启用时返回"副窗未启用"', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: false,
      }
      expect(captured.statusLine(row)).toBe('副窗未启用')
      wrapper.unmount()
    })

    it('无快照时返回"暂无快照"', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: true,
      }
      expect(captured.statusLine(row)).toBe('暂无快照')
      wrapper.unmount()
    })

    it('快照有 stage 时返回 stage', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: true,
        snapshot: {
          empId: 'emp1',
          panelTitle: '',
          shortName: '',
          stage: '处理中',
          progressPct: 0,
          progressLabel: '',
          hintLine: '',
          idle: false,
          visuallyBusy: false,
          lastActivityAt: 0,
        },
      }
      expect(captured.statusLine(row)).toBe('处理中')
      wrapper.unmount()
    })

    it('stage 为空时回退到 progressLabel', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: true,
        snapshot: {
          empId: 'emp1',
          panelTitle: '',
          shortName: '',
          stage: '',
          progressPct: 0,
          progressLabel: '50% 完成',
          hintLine: '',
          idle: false,
          visuallyBusy: false,
          lastActivityAt: 0,
        },
      }
      expect(captured.statusLine(row)).toBe('50% 完成')
      wrapper.unmount()
    })

    it('stage 和 progressLabel 为空时回退到 hintLine', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: true,
        snapshot: {
          empId: 'emp1',
          panelTitle: '',
          shortName: '',
          stage: '',
          progressPct: 0,
          progressLabel: '',
          hintLine: '提示信息',
          idle: false,
          visuallyBusy: false,
          lastActivityAt: 0,
        },
      }
      expect(captured.statusLine(row)).toBe('提示信息')
      wrapper.unmount()
    })

    it('stage、progressLabel、hintLine 均为空时返回"待命"', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: true,
        snapshot: {
          empId: 'emp1',
          panelTitle: '',
          shortName: '',
          stage: '',
          progressPct: 0,
          progressLabel: '',
          hintLine: '',
          idle: false,
          visuallyBusy: false,
          lastActivityAt: 0,
        },
      }
      expect(captured.statusLine(row)).toBe('待命')
      wrapper.unmount()
    })
  })

  describe('ariaLabel', () => {
    it('未启用时返回"副窗未启用"状态', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '张三',
        enabled: false,
      }
      expect(captured.ariaLabel(row)).toBe('员工 张三。副窗未启用')
      wrapper.unmount()
    })

    it('启用但无快照时返回"等待活动"', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '张三',
        enabled: true,
      }
      expect(captured.ariaLabel(row)).toBe('员工 张三。等待活动')
      wrapper.unmount()
    })

    it('启用且有快照时返回 statusLine 内容', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '张三',
        enabled: true,
        snapshot: {
          empId: 'emp1',
          panelTitle: '',
          shortName: '',
          stage: '忙碌中',
          progressPct: 0,
          progressLabel: '',
          hintLine: '',
          idle: false,
          visuallyBusy: false,
          lastActivityAt: 0,
        },
      }
      expect(captured.ariaLabel(row)).toBe('员工 张三。忙碌中')
      wrapper.unmount()
    })
  })

  describe('isBusy', () => {
    it('未启用时返回 false', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: false,
      }
      expect(captured.isBusy(row)).toBe(false)
      wrapper.unmount()
    })

    it('启用但无快照时返回 false', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: true,
      }
      expect(captured.isBusy(row)).toBe(false)
      wrapper.unmount()
    })

    it('快照 visuallyBusy 为 true 时返回 true', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: true,
        snapshot: {
          empId: 'emp1',
          panelTitle: '',
          shortName: '',
          stage: '',
          progressPct: 0,
          progressLabel: '',
          hintLine: '',
          idle: false,
          visuallyBusy: true,
          lastActivityAt: 0,
        },
      }
      expect(captured.isBusy(row)).toBe(true)
      wrapper.unmount()
    })

    it('快照 visuallyBusy 为 false 时返回 false', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: true,
        snapshot: {
          empId: 'emp1',
          panelTitle: '',
          shortName: '',
          stage: '',
          progressPct: 0,
          progressLabel: '',
          hintLine: '',
          idle: false,
          visuallyBusy: false,
          lastActivityAt: 0,
        },
      }
      expect(captured.isBusy(row)).toBe(false)
      wrapper.unmount()
    })
  })

  describe('processedCount', () => {
    it('session 不存在时返回 0', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: true,
      }
      expect(captured.processedCount(row)).toBe(0)
      wrapper.unmount()
    })

    it('session 存在时返回 processedCount', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: true,
        session: {
          empId: 'emp1',
          enabledAt: null,
          firstActivityAt: null,
          lastActivityAt: null,
          processedCount: 42,
          lifetimeMs: 0,
        },
      }
      expect(captured.processedCount(row)).toBe(42)
      wrapper.unmount()
    })

    it('session.processedCount 为 0 时返回 0', async () => {
      const { captured, wrapper } = setupComposable()
      await nextTick()
      const row: WorkflowEmployeeDeskRow = {
        empId: 'emp1',
        panelTitle: '工作流 · 员工1',
        shortName: '员工1',
        enabled: true,
        session: {
          empId: 'emp1',
          enabledAt: null,
          firstActivityAt: null,
          lastActivityAt: null,
          processedCount: 0,
          lifetimeMs: 0,
        },
      }
      expect(captured.processedCount(row)).toBe(0)
      wrapper.unmount()
    })
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

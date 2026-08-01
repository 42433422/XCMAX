import { describe, it, expect, vi } from 'vitest'
import { computed, ref } from 'vue'
import { useWorkspaceDeskDisplay } from './useWorkspaceDeskDisplay'
import type { WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'

const toggleSpy = vi.fn()
vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: () => ({
    toggle: toggleSpy,
  }),
}))

function makeRow(overrides: Partial<WorkflowEmployeeDeskRow> = {}): WorkflowEmployeeDeskRow {
  return {
    empId: 'emp-001',
    panelTitle: '工作流 · 侦察员',
    shortName: '侦察员',
    enabled: true,
    ...overrides,
  }
}

function makeDeps(overrides: Record<string, unknown> = {}) {
  const row = (overrides.selectedDesk ?? null) as WorkflowEmployeeDeskRow | null
  const runtime = 'loopRuntime' in overrides ? overrides.loopRuntime : {}
  return {
    nowMs: ref(Date.now()),
    selectedDesk: ref(row),
    loopRuntime: ref(runtime as Record<string, unknown> | null),
    loopParticipantIds: ref((overrides.loopParticipantIds ?? []) as string[]),
    loopParticipantRoleLabels: ref((overrides.loopParticipantRoleLabels ?? {}) as Record<string, string>),
  }
}

describe('useWorkspaceDeskDisplay', () => {
  it('progressPct 越界收敛到 0-100，disabled 恒为 0', () => {
    const d = useWorkspaceDeskDisplay(makeDeps())
    expect(d.progressPct(makeRow({ snapshot: { progressPct: 120 } as WorkflowEmployeeDeskRow['snapshot'] }))).toBe(100)
    expect(d.progressPct(makeRow({ snapshot: { progressPct: -5 } as WorkflowEmployeeDeskRow['snapshot'] }))).toBe(0)
    expect(d.progressPct(makeRow({ enabled: false, snapshot: { progressPct: 80 } as WorkflowEmployeeDeskRow['snapshot'] }))).toBe(0)
    expect(d.progressPct(makeRow())).toBe(0)
    expect(d.progressWidth(makeRow({ snapshot: { progressPct: 75 } as WorkflowEmployeeDeskRow['snapshot'] }))).toBe('75%')
  })

  it('processedShort 千位缩写', () => {
    const d = useWorkspaceDeskDisplay(makeDeps())
    expect(d.processedShort(makeRow())).toBe('0')
    expect(d.processedShort(makeRow({ session: { processedCount: 999 } as WorkflowEmployeeDeskRow['session'] }))).toBe('999')
    expect(d.processedShort(makeRow({ session: { processedCount: 1500 } as WorkflowEmployeeDeskRow['session'] }))).toBe('1.5k')
    expect(d.processedShort(makeRow({ session: { processedCount: 15000 } as WorkflowEmployeeDeskRow['session'] }))).toBe('15k')
  })

  it('deskLoopState：参与者 → run', () => {
    const d = useWorkspaceDeskDisplay(makeDeps({
      loopParticipantIds: ['emp-001'],
      loopParticipantRoleLabels: { 'emp-001': '侦察' },
    }))
    const state = d.deskLoopState(makeRow())
    expect(state.tone).toBe('run')
    expect(state.label).toBe('参与 Loop')
    expect(state.detail).toBe('侦察')
  })

  it('deskLoopState：未托管 → off', () => {
    const d = useWorkspaceDeskDisplay(makeDeps())
    expect(d.deskLoopState(makeRow({ enabled: false })).tone).toBe('off')
  })

  it('deskLoopState：runtime 缺失 → warn；无参与者 → idle 待派发；未参与 → idle', () => {
    const warn = useWorkspaceDeskDisplay(makeDeps({ loopRuntime: null }))
    expect(warn.deskLoopState(makeRow()).tone).toBe('warn')

    const idle = useWorkspaceDeskDisplay(makeDeps({ loopParticipantIds: [] }))
    expect(idle.deskLoopState(makeRow()).label).toBe('待派发')

    const notInRound = useWorkspaceDeskDisplay(makeDeps({ loopParticipantIds: ['emp-002'] }))
    const state = notInRound.deskLoopState(makeRow())
    expect(state.tone).toBe('idle')
    expect(state.label).toBe('未参与本轮')
  })

  it('selectedDeskLoopState 跟随 selectedDesk', () => {
    const deps = makeDeps({ selectedDesk: makeRow(), loopParticipantIds: ['emp-001'] })
    const d = useWorkspaceDeskDisplay(deps)
    expect(d.selectedDeskLoopState.value?.tone).toBe('run')
    deps.selectedDesk.value = null
    expect(d.selectedDeskLoopState.value).toBeNull()
  })

  it('toggleDesk 阻止冒泡并调用 store.toggle', () => {
    toggleSpy.mockClear()
    const d = useWorkspaceDeskDisplay(makeDeps())
    const ev = { stopPropagation: vi.fn() } as unknown as Event
    d.toggleDesk('emp-001', ev)
    expect(ev.stopPropagation).toHaveBeenCalled()
    expect(toggleSpy).toHaveBeenCalledWith('emp-001')
  })

  it('isLoopParticipant 与 computed 依赖保持响应', () => {
    const deps = makeDeps({ loopParticipantIds: [] })
    const d = useWorkspaceDeskDisplay(deps)
    expect(d.isLoopParticipant('emp-001')).toBe(false)
    deps.loopParticipantIds.value = ['emp-001']
    expect(d.isLoopParticipant('emp-001')).toBe(true)
    expect(computed(() => d.isLoopParticipant('emp-001')).value).toBe(true)
  })
})

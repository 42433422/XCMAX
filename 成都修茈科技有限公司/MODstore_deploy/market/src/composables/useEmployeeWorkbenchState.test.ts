import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useEmployeeWorkbenchState } from './useEmployeeWorkbenchState'
import { api } from '../api'

vi.mock('../api', () => ({
  api: {
    listEmployeeEligibleWorkflows: vi.fn(),
  },
}))

describe('useEmployeeWorkbenchState', () => {
  beforeEach(() => {
    vi.mocked(api.listEmployeeEligibleWorkflows).mockReset()
  })

  it('resolves workflow id from editor JSON before manifest fallback', () => {
    const state = useEmployeeWorkbenchState({
      parseWorkflowIdFromEntry: (entry: any) => Number(entry.workflow_id || 0),
      inferWorkflowIdFromManifest: () => 99,
    })

    state.workflowJsonText.value = '{"workflow_id": 42}'
    state.linkedManifestSnapshot.value = { workflow_employees: [{ workflow_id: 99 }] }

    expect(state.resolvedWorkflowId.value).toBe(42)
    expect(state.safeResolvedWorkflowId.value).toBe(42)
  })

  it('falls back to scanned package workflow id', () => {
    const state = useEmployeeWorkbenchState({
      parseWorkflowIdFromEntry: () => 0,
      inferWorkflowIdFromManifest: () => 0,
    })

    state.packageManifestWorkflowId.value = 17

    expect(state.packageScanFlashClass.value).toBe('flash-info')
    state.packageScanKind.value = 'ok'
    expect(state.packageScanFlashClass.value).toBe('flash-success')
    state.packageScanKind.value = 'warn'
    expect(state.packageScanFlashClass.value).toBe('flash-warn')
    expect(state.resolvedWorkflowId.value).toBe(17)
  })

  it('uses manifest fallback and safe id guards', () => {
    const state = useEmployeeWorkbenchState({
      parseWorkflowIdFromEntry: () => 0,
      inferWorkflowIdFromManifest: (_manifest: any, index: number) => index + 70,
    })

    state.workflowJsonText.value = '{bad json'
    state.linkedWorkflowIndex.value = 2
    state.linkedManifestSnapshot.value = { workflow_employees: [{ workflow_id: 72 }] }
    expect(state.resolvedWorkflowId.value).toBe(72)
    expect(state.safeResolvedWorkflowId.value).toBe(72)

    state.linkedManifestSnapshot.value = null
    state.packageManifestWorkflowId.value = Number.NaN
    expect(state.resolvedWorkflowId.value).toBe(0)
    expect(state.safeResolvedWorkflowId.value).toBe(0)
    expect(state.selectedWorkflowStatus.value).toBeNull()
    expect(state.workflowGate.value).toBe('idle')
    expect(state.workflowGateMessage.value).toBe('请先选择已通过沙箱测试的工作流')
  })

  it('only passes workflow gate for eligible sandboxed workflows', () => {
    const state = useEmployeeWorkbenchState({
      parseWorkflowIdFromEntry: (entry: any) => Number(entry.workflow_id || 0),
      inferWorkflowIdFromManifest: () => 0,
    })

    state.workflowJsonText.value = '{"workflow_id": 42}'
    state.allWorkflowOptions.value = [
      { id: 42, sandbox_status: { status: 'stale' } },
      { id: 99, sandbox_status: { status: 'pass' } },
    ]
    state.eligibleWorkflows.value = [{ id: 99, sandbox_status: { status: 'pass' } }]

    expect(state.workflowGate.value).toBe('stale')
    expect(state.workflowGatePass.value).toBe(false)

    state.workflowJsonText.value = '{"workflow_id": 99}'

    expect(state.workflowGate.value).toBe('pass')
    expect(state.workflowGatePass.value).toBe(true)
    expect(state.workflowGateMessage.value).toContain('已通过沙箱测试')
  })

  it('reports workflow gate loading, errors, untested and failed statuses', () => {
    const state = useEmployeeWorkbenchState({
      parseWorkflowIdFromEntry: (entry: any) => Number(entry.workflow_id || 0),
      inferWorkflowIdFromManifest: () => 0,
    })

    state.workflowGateLoading.value = true
    expect(state.workflowGate.value).toBe('loading')
    expect(state.workflowGateMessage.value).toBe('正在读取工作流沙箱状态')

    state.workflowGateLoading.value = false
    state.workflowGateError.value = 'gate down'
    expect(state.workflowGateMessage.value).toBe('gate down')

    state.workflowGateError.value = ''
    state.workflowJsonText.value = '{"workflow_id": 7}'
    state.allWorkflowOptions.value = [{ id: 7, sandbox_status: { status: 'untested' } }]
    expect(state.workflowGate.value).toBe('untested')
    expect(state.workflowGateMessage.value).toContain('尚未运行沙箱测试')

    state.allWorkflowOptions.value = [{ id: 7, sandbox_status: { status: 'fail' } }]
    expect(state.workflowGate.value).toBe('fail')
    expect(state.workflowGateMessage.value).toContain('未通过')
  })

  it('loads eligible workflows and records failures', async () => {
    vi.mocked(api.listEmployeeEligibleWorkflows).mockResolvedValueOnce({
      workflows: [{ id: 1, sandbox_status: { status: 'pass' } }],
      all_workflows: [{ id: 1 }, { id: 2, sandbox_status: { status: 'stale' } }],
    } as any)
    const state = useEmployeeWorkbenchState({
      parseWorkflowIdFromEntry: () => 0,
      inferWorkflowIdFromManifest: () => 0,
    })

    await state.loadEligibleWorkflows()
    expect(state.workflowGateLoading.value).toBe(false)
    expect(state.eligibleWorkflows.value).toHaveLength(1)
    expect(state.allWorkflowOptions.value).toHaveLength(2)

    vi.mocked(api.listEmployeeEligibleWorkflows).mockRejectedValueOnce(new Error('eligible down'))
    await state.loadEligibleWorkflows()
    expect(state.eligibleWorkflows.value).toEqual([])
    expect(state.allWorkflowOptions.value).toEqual([])
    expect(state.workflowGateError.value).toBe('eligible down')
  })
})

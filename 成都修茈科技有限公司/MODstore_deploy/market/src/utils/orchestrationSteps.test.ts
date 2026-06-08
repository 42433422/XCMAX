import { describe, expect, it } from 'vitest'
import {
  EMPLOYEE_ORCH_STEP_IDS,
  ORCH_STEP_VISUAL,
  computeOrchProgress,
  mergeOrchStepsMonotonic,
  orchStepEmployee,
  resolveOrchStepId,
} from './orchestrationSteps'

describe('orchestrationSteps', () => {
  it('covers all 14 employee step ids', () => {
    expect(EMPLOYEE_ORCH_STEP_IDS).toHaveLength(14)
    expect(EMPLOYEE_ORCH_STEP_IDS).toContain('six_dim_gate')
    for (const id of EMPLOYEE_ORCH_STEP_IDS) {
      expect(ORCH_STEP_VISUAL[id]?.name).toBeTruthy()
    }
  })

  it('resolves by backend id even when label changes', () => {
    expect(resolveOrchStepId({ id: 'generate', label: '任意新文案' })).toBe('generate')
    expect(orchStepEmployee({ id: 'complete', label: '完成' })).toBe('完成')
  })

  it('falls back to label map', () => {
    expect(resolveOrchStepId({ id: '', label: '理解需求' })).toBe('spec')
  })

  it('counts skipped as terminal in progress', () => {
    const steps = [
      { id: 'spec', status: 'done' },
      { id: 'host_check', status: 'skipped' },
      { id: 'complete', status: 'pending' },
    ]
    expect(computeOrchProgress(steps).done).toBe(2)
  })

  it('mergeOrchStepsMonotonic prevents status regression', () => {
    const prev = [{ id: 'generate', status: 'done', label: '生成产物' }]
    const incoming = [{ id: 'generate', status: 'pending', label: '生成产物' }]
    const merged = mergeOrchStepsMonotonic(prev, incoming)
    expect(merged[0].status).toBe('done')
  })
})

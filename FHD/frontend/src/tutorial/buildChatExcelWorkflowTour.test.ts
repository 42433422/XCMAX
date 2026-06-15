import { describe, expect, it } from 'vitest'
import { buildChatExcelWorkflowSteps } from './buildChatExcelWorkflowTour'
import { TUTORIAL_DEPT_EMPLOYEE_SAMPLE_XLSX, TUTORIAL_SAMPLE_NAME_PREFIX } from '@/constants/tutorialSamples'

describe('buildChatExcelWorkflowSteps', () => {
  it('covers dialogue, excel import, verify and cleanup', () => {
    const steps = buildChatExcelWorkflowSteps()
    const ids = steps.map((s) => s.id)
    expect(ids[0]).toBe('chat-dialogue-basics')
    expect(ids).toContain('tutorial-excel-upload')
    expect(ids).toContain('tutorial-excel-import-customers')
    expect(ids).toContain('tutorial-cleanup-departments')
    expect(ids[ids.length - 1]).toBe('tutorial-excel-flow-complete')
    const sampleStep = steps.find((s) => s.id === 'tutorial-excel-sample')
    expect(sampleStep?.description).toContain(TUTORIAL_DEPT_EMPLOYEE_SAMPLE_XLSX)
    expect(sampleStep?.description).toContain(TUTORIAL_SAMPLE_NAME_PREFIX)
  })
})

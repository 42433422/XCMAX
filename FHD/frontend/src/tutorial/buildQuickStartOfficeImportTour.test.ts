import { describe, expect, it } from 'vitest'
import { buildQuickStartOfficeImportSteps } from './buildQuickStartOfficeImportTour'

describe('buildQuickStartOfficeImportSteps', () => {
  it('covers excel x2, word, and cleanup after office pack', () => {
    const steps = buildQuickStartOfficeImportSteps()
    const ids = steps.map((s) => s.id)
    expect(ids[0]).toBe('quickstart-import-go-chat')
    expect(ids).toContain('quickstart-import-excel-a')
    expect(ids).toContain('quickstart-import-excel-b')
    expect(ids).toContain('quickstart-import-word')
    expect(ids[ids.length - 1]).toBe('quickstart-import-word-result')
    expect(steps.every((s) => s.routeName === 'chat')).toBe(true)
  })
})

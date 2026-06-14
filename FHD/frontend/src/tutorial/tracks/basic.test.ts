import { describe, it, expect } from 'vitest'
import { buildBasicSteps } from './basic'

describe('buildBasicSteps', () => {
  it('returns an ordered list of tutorial steps', () => {
    const steps = buildBasicSteps({ industryId: '考勤', mods: [], visibleNav: [], isProMode: false } as never)
    expect(Array.isArray(steps)).toBe(true)
    expect(steps.length).toBeGreaterThan(3)
    expect(steps[0].id).toBe('chat-entry')
    for (const s of steps) {
      expect(typeof s.id).toBe('string')
      expect(typeof s.title).toBe('string')
      expect(s.actionType).toBeDefined()
    }
  })

  it('produces unique step ids', () => {
    const steps = buildBasicSteps({ industryId: '', mods: [], visibleNav: [], isProMode: false } as never)
    const ids = steps.map((s) => s.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})

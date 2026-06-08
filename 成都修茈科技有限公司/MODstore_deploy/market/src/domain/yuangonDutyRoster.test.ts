import { describe, expect, it } from 'vitest'
import { YUANGON_AREAS, ALL_PLANNED_YUANGON_PKG_IDS } from './yuangonDutyRoster'

describe('YUANGON_AREAS', () => {
  it('has expected area keys', () => {
    expect(Object.keys(YUANGON_AREAS)).toContain('site-and-marketing')
    expect(Object.keys(YUANGON_AREAS)).toContain('server-and-ops')
    expect(Object.keys(YUANGON_AREAS)).toContain('modstore-backend')
    expect(Object.keys(YUANGON_AREAS)).toContain('modstore-frontend')
    expect(Object.keys(YUANGON_AREAS)).toContain('platform-core')
    expect(Object.keys(YUANGON_AREAS)).toContain('quality-and-docs')
  })

  it('each area has label and ids', () => {
    for (const area of Object.values(YUANGON_AREAS)) {
      expect(typeof area.label).toBe('string')
      expect(area.label.length).toBeGreaterThan(0)
      expect(Array.isArray(area.ids)).toBe(true)
      expect(area.ids.length).toBeGreaterThan(0)
    }
  })

  it('all ids are unique strings', () => {
    const allIds = Object.values(YUANGON_AREAS).flatMap((a) => a.ids)
    const uniqueIds = new Set(allIds)
    expect(uniqueIds.size).toBe(allIds.length)
  })
})

describe('ALL_PLANNED_YUANGON_PKG_IDS', () => {
  it('is a Set', () => {
    expect(ALL_PLANNED_YUANGON_PKG_IDS).toBeInstanceOf(Set)
  })

  it('contains all ids from areas', () => {
    const allIds = Object.values(YUANGON_AREAS).flatMap((a) => a.ids)
    for (const id of allIds) {
      expect(ALL_PLANNED_YUANGON_PKG_IDS.has(id)).toBe(true)
    }
  })

  it('does not contain arbitrary strings', () => {
    expect(ALL_PLANNED_YUANGON_PKG_IDS.has('nonexistent-id')).toBe(false)
    expect(ALL_PLANNED_YUANGON_PKG_IDS.has('')).toBe(false)
  })

  it('has expected count of ids', () => {
    const expectedCount = Object.values(YUANGON_AREAS).reduce((sum, a) => sum + a.ids.length, 0)
    expect(ALL_PLANNED_YUANGON_PKG_IDS.size).toBe(expectedCount)
  })
})

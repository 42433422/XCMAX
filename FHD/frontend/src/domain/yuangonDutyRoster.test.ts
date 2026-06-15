import { describe, expect, it } from 'vitest'
import {
  ALL_PLANNED_YUANGON_PKG_IDS,
  YUANGON_AREAS,
  YUANGON_PKG_ROLE_LABELS,
  SIX_LINE_DEPARTMENTS,
  DEPARTMENT_ORDER,
  DEPARTMENT_COLORS,
  CRAFT_SUBZONE_ID,
} from './yuangonDutyRoster'

describe('yuangonDutyRoster', () => {
  it('aggregates all planned pkg ids from areas', () => {
    const fromAreas = new Set(Object.values(YUANGON_AREAS).flatMap((a) => a.ids))
    expect(ALL_PLANNED_YUANGON_PKG_IDS.size).toBe(fromAreas.size)
    expect(ALL_PLANNED_YUANGON_PKG_IDS.has('fhd-core-maintainer')).toBe(true)
  })

  it('has role labels for known pkg ids', () => {
    expect(YUANGON_PKG_ROLE_LABELS['fhd-core-maintainer']).toContain('FHD')
    expect(YUANGON_PKG_ROLE_LABELS['intent-analyst']).toBeTruthy()
  })

  it('defines six-line departments', () => {
    expect(Object.keys(SIX_LINE_DEPARTMENTS)).toEqual(expect.arrayContaining(DEPARTMENT_ORDER))
    expect(SIX_LINE_DEPARTMENTS.prod_mod.subzones[CRAFT_SUBZONE_ID].ids.length).toBe(13)
  })

  it('assigns department colors', () => {
    for (const id of DEPARTMENT_ORDER) {
      expect(DEPARTMENT_COLORS[id]).toMatch(/^#/)
    }
  })
})

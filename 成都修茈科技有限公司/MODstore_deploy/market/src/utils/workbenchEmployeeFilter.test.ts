import { describe, expect, it } from 'vitest'
import { isPlannedDutyRosterPkgId, filterOutPlannedDutyEmployees } from './workbenchEmployeeFilter'

describe('isPlannedDutyRosterPkgId', () => {
  it('returns true for a known planned duty roster pkg id', () => {
    expect(isPlannedDutyRosterPkgId('site-content-editor')).toBe(true)
    expect(isPlannedDutyRosterPkgId('nginx-config-engineer')).toBe(true)
    expect(isPlannedDutyRosterPkgId('modstore-backend-api')).toBe(true)
  })

  it('returns false for unknown pkg id', () => {
    expect(isPlannedDutyRosterPkgId('my-custom-employee')).toBe(false)
    expect(isPlannedDutyRosterPkgId('random-id')).toBe(false)
  })

  it('returns false for empty string', () => {
    expect(isPlannedDutyRosterPkgId('')).toBe(false)
  })
})

describe('filterOutPlannedDutyEmployees', () => {
  it('filters out planned duty employees', () => {
    const rows = [
      { id: 'site-content-editor', name: 'Site Editor' },
      { id: 'my-custom-employee', name: 'Custom' },
      { id: 'nginx-config-engineer', name: 'Nginx' },
    ]
    const result = filterOutPlannedDutyEmployees(rows)
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('my-custom-employee')
  })

  it('keeps rows without id', () => {
    const rows = [
      { name: 'No ID' },
      { id: '', name: 'Empty ID' },
    ]
    const result = filterOutPlannedDutyEmployees(rows)
    expect(result).toHaveLength(2)
  })

  it('returns empty array for empty input', () => {
    expect(filterOutPlannedDutyEmployees([])).toEqual([])
  })

  it('keeps all rows when none match', () => {
    const rows = [
      { id: 'custom-1', name: 'Custom 1' },
      { id: 'custom-2', name: 'Custom 2' },
    ]
    const result = filterOutPlannedDutyEmployees(rows)
    expect(result).toHaveLength(2)
  })
})

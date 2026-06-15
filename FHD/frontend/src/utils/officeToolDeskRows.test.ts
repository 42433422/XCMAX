import { describe, expect, it } from 'vitest'
import { OFFICE_EMPLOYEE_PKG_IDS } from '@/constants/officeEmployeePack'
import {
  buildOfficeToolDeskRows,
  officePackIdToShortLabel,
  resolveOfficeInstalledPackIds,
} from './officeToolDeskRows'

describe('officeToolDeskRows', () => {
  it('labels office pack ids for graph display', () => {
    expect(officePackIdToShortLabel('excel-generate-employee')).toBe('Excel·写')
    expect(officePackIdToShortLabel('csv-full-read-employee')).toBe('CSV·读')
  })

  it('builds L1 tool desk rows', () => {
    const rows = buildOfficeToolDeskRows(['excel-generate-employee'])
    expect(rows).toHaveLength(1)
    expect(rows[0]?.empId).toBe('excel-generate-employee')
    expect(rows[0]?.hostModId).toBe('xcagi-office-employee-pack-bridge')
  })

  it('resolves installed ids from planner status fallback', () => {
    const allMissing = resolveOfficeInstalledPackIds({
      installed_employee_pack_count: 0,
      registered_tool_count: 0,
      registered_tool_names: [],
      office_catalog_count: OFFICE_EMPLOYEE_PKG_IDS.length,
      office_installed_count: 0,
      office_installed_ids: [],
      missing_office_pack_ids: [...OFFICE_EMPLOYEE_PKG_IDS],
      office_ready: false,
      runtime_missing_pack_ids: [],
    })
    expect(allMissing).toEqual([])

    const ready = resolveOfficeInstalledPackIds({
      installed_employee_pack_count: 10,
      registered_tool_count: 10,
      registered_tool_names: [],
      office_catalog_count: OFFICE_EMPLOYEE_PKG_IDS.length,
      office_installed_count: OFFICE_EMPLOYEE_PKG_IDS.length,
      office_installed_ids: [],
      missing_office_pack_ids: [],
      office_ready: true,
      runtime_missing_pack_ids: [],
    })
    expect(ready).toEqual([...OFFICE_EMPLOYEE_PKG_IDS])
  })
})

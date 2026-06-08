import { describe, expect, it } from 'vitest'
import {
  OFFICE_AUX_PACK_1_PKG_IDS,
  OFFICE_EMPLOYEE_PKG_IDS,
  employeePackIconKind,
  isOfficeAuxPack1Pkg,
  isOfficeEmployeePkg,
} from './officeEmployeePack'

describe('officeEmployeePack', () => {
  it('main office pack has 10 tabular employees without json-report', () => {
    expect(OFFICE_EMPLOYEE_PKG_IDS).toHaveLength(10)
    expect(OFFICE_EMPLOYEE_PKG_IDS).not.toContain('json-report-employee')
  })

  it('aux pack 1 contains json-report-employee only', () => {
    expect(OFFICE_AUX_PACK_1_PKG_IDS).toEqual(['json-report-employee'])
  })

  it('classifies pkg ids for icons and membership', () => {
    expect(isOfficeEmployeePkg('excel-generate-employee')).toBe(true)
    expect(isOfficeEmployeePkg('json-report-employee')).toBe(false)
    expect(isOfficeAuxPack1Pkg('json-report-employee')).toBe(true)
    expect(employeePackIconKind('json-report-employee')).toBe('report')
    expect(employeePackIconKind('word-generate-employee')).toBe('word')
  })
})

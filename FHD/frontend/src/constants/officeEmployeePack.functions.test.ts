import { describe, it, expect } from 'vitest'
import {
  OFFICE_EMPLOYEE_PKG_IDS,
  EXCEL_FULL_READ_EMPLOYEE_ID,
  WORD_FULL_READ_EMPLOYEE_ID,
  OFFICE_AUX_PACK_1_PKG_IDS,
  OFFICE_EMPLOYEE_COLLECTION,
  OFFICE_AUX_PACK_1_COLLECTION,
  OFFICE_GROUP_ORDER,
  OFFICE_AUX_GROUP_ORDER,
  OFFICE_GROUP_LABELS,
  employeePackIconKind,
  isOfficeEmployeePkg,
  isOfficeAuxPack1Pkg,
  employeePackRole,
} from './officeEmployeePack'

describe('officeEmployeePack constants and functions', () => {
  describe('OFFICE_EMPLOYEE_PKG_IDS', () => {
    it('is a non-empty array', () => {
      expect(OFFICE_EMPLOYEE_PKG_IDS.length).toBeGreaterThan(0)
    })

    it('contains excel-generate-employee', () => {
      expect(OFFICE_EMPLOYEE_PKG_IDS).toContain('excel-generate-employee')
    })

    it('contains word-full-read-employee', () => {
      expect(OFFICE_EMPLOYEE_PKG_IDS).toContain('word-full-read-employee')
    })
  })

  describe('EXCEL_FULL_READ_EMPLOYEE_ID', () => {
    it('is excel-full-read-employee', () => {
      expect(EXCEL_FULL_READ_EMPLOYEE_ID).toBe('excel-full-read-employee')
    })
  })

  describe('WORD_FULL_READ_EMPLOYEE_ID', () => {
    it('is word-full-read-employee', () => {
      expect(WORD_FULL_READ_EMPLOYEE_ID).toBe('word-full-read-employee')
    })
  })

  describe('OFFICE_AUX_PACK_1_PKG_IDS', () => {
    it('is a non-empty array', () => {
      expect(OFFICE_AUX_PACK_1_PKG_IDS.length).toBeGreaterThan(0)
    })

    it('contains json-report-employee', () => {
      expect(OFFICE_AUX_PACK_1_PKG_IDS).toContain('json-report-employee')
    })

    it('contains chart-bar-employee', () => {
      expect(OFFICE_AUX_PACK_1_PKG_IDS).toContain('chart-bar-employee')
    })
  })

  describe('OFFICE_EMPLOYEE_COLLECTION', () => {
    it('is office_employee_pack', () => {
      expect(OFFICE_EMPLOYEE_COLLECTION).toBe('office_employee_pack')
    })
  })

  describe('OFFICE_AUX_PACK_1_COLLECTION', () => {
    it('is office_employee_aux_pack_1', () => {
      expect(OFFICE_AUX_PACK_1_COLLECTION).toBe('office_employee_aux_pack_1')
    })
  })

  describe('OFFICE_GROUP_ORDER', () => {
    it('contains ppt excel csv pdf word', () => {
      expect(OFFICE_GROUP_ORDER).toEqual(['ppt', 'excel', 'csv', 'pdf', 'word'])
    })
  })

  describe('OFFICE_AUX_GROUP_ORDER', () => {
    it('contains report chart', () => {
      expect(OFFICE_AUX_GROUP_ORDER).toEqual(['report', 'chart'])
    })
  })

  describe('OFFICE_GROUP_LABELS', () => {
    it('has label for ppt', () => {
      expect(OFFICE_GROUP_LABELS.ppt).toBe('PPT')
    })

    it('has label for excel', () => {
      expect(OFFICE_GROUP_LABELS.excel).toBe('Excel')
    })

    it('has label for generic', () => {
      expect(OFFICE_GROUP_LABELS.generic).toBe('其他')
    })
  })

  describe('employeePackIconKind', () => {
    it('returns ppt for ppt- prefix', () => {
      expect(employeePackIconKind('ppt-generate-employee')).toBe('ppt')
    })

    it('returns excel for excel- prefix', () => {
      expect(employeePackIconKind('excel-generate-employee')).toBe('excel')
    })

    it('returns csv for csv- prefix', () => {
      expect(employeePackIconKind('csv-generate-employee')).toBe('csv')
    })

    it('returns pdf for pdf- prefix', () => {
      expect(employeePackIconKind('pdf-generate-employee')).toBe('pdf')
    })

    it('returns word for word- prefix', () => {
      expect(employeePackIconKind('word-generate-employee')).toBe('word')
    })

    it('returns report for json-report prefix', () => {
      expect(employeePackIconKind('json-report-employee')).toBe('report')
    })

    it('returns chart for chart- prefix', () => {
      expect(employeePackIconKind('chart-bar-employee')).toBe('chart')
    })

    it('returns office for exact match in OFFICE_EMPLOYEE_PKG_IDS', () => {
      expect(employeePackIconKind('excel-generate-employee')).toBe('excel')
    })

    it('returns generic for unknown id', () => {
      expect(employeePackIconKind('unknown-employee')).toBe('generic')
    })

    it('returns generic for empty string', () => {
      expect(employeePackIconKind('')).toBe('generic')
    })

    it('returns generic for null input', () => {
      expect(employeePackIconKind(null)).toBe('generic')
    })

    it('returns generic for undefined input', () => {
      expect(employeePackIconKind(undefined)).toBe('generic')
    })

    it('is case-insensitive', () => {
      expect(employeePackIconKind('PPT-Generate-Employee')).toBe('ppt')
    })
  })

  describe('isOfficeEmployeePkg', () => {
    it('returns true for excel-generate-employee', () => {
      expect(isOfficeEmployeePkg('excel-generate-employee')).toBe(true)
    })

    it('returns true for word-full-read-employee', () => {
      expect(isOfficeEmployeePkg('word-full-read-employee')).toBe(true)
    })

    it('returns false for unknown id', () => {
      expect(isOfficeEmployeePkg('unknown-employee')).toBe(false)
    })

    it('returns false for empty string', () => {
      expect(isOfficeEmployeePkg('')).toBe(false)
    })

    it('returns false for null input', () => {
      expect(isOfficeEmployeePkg(null)).toBe(false)
    })

    it('returns false for undefined input', () => {
      expect(isOfficeEmployeePkg(undefined)).toBe(false)
    })
  })

  describe('isOfficeAuxPack1Pkg', () => {
    it('returns true for json-report-employee', () => {
      expect(isOfficeAuxPack1Pkg('json-report-employee')).toBe(true)
    })

    it('returns true for chart-bar-employee', () => {
      expect(isOfficeAuxPack1Pkg('chart-bar-employee')).toBe(true)
    })

    it('returns false for office employee id', () => {
      expect(isOfficeAuxPack1Pkg('excel-generate-employee')).toBe(false)
    })

    it('returns false for unknown id', () => {
      expect(isOfficeAuxPack1Pkg('unknown-employee')).toBe(false)
    })

    it('returns false for empty string', () => {
      expect(isOfficeAuxPack1Pkg('')).toBe(false)
    })

    it('returns false for null input', () => {
      expect(isOfficeAuxPack1Pkg(null)).toBe(false)
    })
  })

  describe('employeePackRole', () => {
    it('returns read for full-read employee', () => {
      expect(employeePackRole('excel-full-read-employee')).toBe('read')
    })

    it('returns read for -read-employee suffix', () => {
      expect(employeePackRole('word-read-employee')).toBe('read')
    })

    it('returns generate for generate employee', () => {
      expect(employeePackRole('excel-generate-employee')).toBe('generate')
    })

    it('returns report for json-report employee', () => {
      expect(employeePackRole('json-report-employee')).toBe('report')
    })

    it('returns generate for chart- prefix', () => {
      expect(employeePackRole('chart-bar-employee')).toBe('generate')
    })

    it('returns empty string for unknown id', () => {
      expect(employeePackRole('unknown-employee')).toBe('')
    })

    it('returns empty string for empty string', () => {
      expect(employeePackRole('')).toBe('')
    })

    it('returns empty string for null input', () => {
      expect(employeePackRole(null)).toBe('')
    })

    it('returns empty string for undefined input', () => {
      expect(employeePackRole(undefined)).toBe('')
    })
  })
})

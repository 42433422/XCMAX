import { describe, it, expect, beforeEach } from 'vitest'
import {
  OFFICE_EMPLOYEE_PACK_BRIDGE_MOD_ID,
  LS_OFFICE_EMPLOYEE_PACK_MOD_PAGES_ENABLED,
  readOfficeEmployeePackModPagesEnabled,
  setOfficeEmployeePackModPagesEnabled,
} from './officeEmployeePackMod'

describe('officeEmployeePackMod constants and functions', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('OFFICE_EMPLOYEE_PACK_BRIDGE_MOD_ID', () => {
    it('is the office employee pack bridge mod id', () => {
      expect(OFFICE_EMPLOYEE_PACK_BRIDGE_MOD_ID).toBe('xcagi-office-employee-pack-bridge')
    })
  })

  describe('LS_OFFICE_EMPLOYEE_PACK_MOD_PAGES_ENABLED', () => {
    it('is the localStorage key string', () => {
      expect(LS_OFFICE_EMPLOYEE_PACK_MOD_PAGES_ENABLED).toBe('xcagi_office_employee_pack_mod_pages_enabled')
    })
  })

  describe('readOfficeEmployeePackModPagesEnabled', () => {
    it('returns false when localStorage is empty', () => {
      expect(readOfficeEmployeePackModPagesEnabled()).toBe(false)
    })

    it('returns false when value is 0', () => {
      localStorage.setItem(LS_OFFICE_EMPLOYEE_PACK_MOD_PAGES_ENABLED, '0')
      expect(readOfficeEmployeePackModPagesEnabled()).toBe(false)
    })

    it('returns true when value is 1', () => {
      localStorage.setItem(LS_OFFICE_EMPLOYEE_PACK_MOD_PAGES_ENABLED, '1')
      expect(readOfficeEmployeePackModPagesEnabled()).toBe(true)
    })

    it('returns false for arbitrary string', () => {
      localStorage.setItem(LS_OFFICE_EMPLOYEE_PACK_MOD_PAGES_ENABLED, 'yes')
      expect(readOfficeEmployeePackModPagesEnabled()).toBe(false)
    })
  })

  describe('setOfficeEmployeePackModPagesEnabled', () => {
    it('sets value to 1 when true', () => {
      setOfficeEmployeePackModPagesEnabled(true)
      expect(localStorage.getItem(LS_OFFICE_EMPLOYEE_PACK_MOD_PAGES_ENABLED)).toBe('1')
    })

    it('sets value to 0 when false', () => {
      setOfficeEmployeePackModPagesEnabled(false)
      expect(localStorage.getItem(LS_OFFICE_EMPLOYEE_PACK_MOD_PAGES_ENABLED)).toBe('0')
    })

    it('read reflects write', () => {
      setOfficeEmployeePackModPagesEnabled(true)
      expect(readOfficeEmployeePackModPagesEnabled()).toBe(true)
      setOfficeEmployeePackModPagesEnabled(false)
      expect(readOfficeEmployeePackModPagesEnabled()).toBe(false)
    })
  })
})

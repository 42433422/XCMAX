import { describe, it, expect } from 'vitest'
import {
  ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU,
  ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES,
  COATING_CUSTOM_MOD_FALLBACK_OVERRIDES,
  SUNBIRD_CLIENT_MOD_FALLBACK_MENU,
  SUNBIRD_CLIENT_MOD_FALLBACK_OVERRIDES,
  buildAttendanceIndustryModStub,
  buildSunbirdClientModStub,
  buildCoatingCustomModStub,
} from './sunbirdClientMod'

describe('sunbirdClientMod constants and functions', () => {
  describe('ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU', () => {
    it('is a non-empty array', () => {
      expect(ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU.length).toBeGreaterThan(0)
    })

    it('puts the attendance dashboard first', () => {
      expect(ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU[0].id).toBe('attendance-industry-dashboard')
    })

    it('uses the dashboard as the primary attendance path', () => {
      expect(ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU[0].path).toBe('/attendance-industry/dashboard')
    })
  })

  describe('ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES', () => {
    it('is an empty array', () => {
      expect(ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES).toEqual([])
    })
  })

  describe('COATING_CUSTOM_MOD_FALLBACK_OVERRIDES', () => {
    it('is a non-empty array', () => {
      expect(COATING_CUSTOM_MOD_FALLBACK_OVERRIDES.length).toBeGreaterThan(0)
    })

    it('contains products override', () => {
      const products = COATING_CUSTOM_MOD_FALLBACK_OVERRIDES.find((o) => o.key === 'products')
      expect(products?.label).toBe('产品管理')
    })
  })

  describe('SUNBIRD_CLIENT_MOD_FALLBACK_MENU (deprecated alias)', () => {
    it('is the same as ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU', () => {
      expect(SUNBIRD_CLIENT_MOD_FALLBACK_MENU).toBe(ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU)
    })
  })

  describe('SUNBIRD_CLIENT_MOD_FALLBACK_OVERRIDES (deprecated alias)', () => {
    it('is the same as ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES', () => {
      expect(SUNBIRD_CLIENT_MOD_FALLBACK_OVERRIDES).toBe(ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES)
    })
  })

  describe('buildAttendanceIndustryModStub', () => {
    it('returns a ModInfo object', () => {
      const stub = buildAttendanceIndustryModStub()
      expect(stub).toHaveProperty('id')
      expect(stub).toHaveProperty('name')
      expect(stub).toHaveProperty('version')
    })

    it('has primary set to true', () => {
      expect(buildAttendanceIndustryModStub().primary).toBe(true)
    })

    it('has industry id set to 考勤', () => {
      expect(buildAttendanceIndustryModStub().industry?.id).toBe('考勤')
    })

    it('has menu with attendance-industry-dashboard', () => {
      const stub = buildAttendanceIndustryModStub()
      expect(stub.menu?.[0]?.id).toBe('attendance-industry-dashboard')
    })

    it('has frontend pro_entry_path', () => {
      expect(buildAttendanceIndustryModStub().frontend?.pro_entry_path).toBe('/attendance-industry/dashboard')
    })

    it('returns a new menu array each call (not shared reference)', () => {
      const stub1 = buildAttendanceIndustryModStub()
      const stub2 = buildAttendanceIndustryModStub()
      expect(stub1.menu).not.toBe(stub2.menu)
      expect(stub1.menu).toEqual(stub2.menu)
    })
  })

  describe('buildSunbirdClientModStub', () => {
    it('returns the unified attendance fallback', () => {
      expect(buildSunbirdClientModStub().id).toBe('attendance-industry')
    })

    it('has the neutral attendance name', () => {
      expect(buildSunbirdClientModStub().name).toBe('通用考勤模块')
    })

    it('has primary set to true', () => {
      expect(buildSunbirdClientModStub().primary).toBe(true)
    })

    it('has industry id 考勤', () => {
      expect(buildSunbirdClientModStub().industry?.id).toBe('考勤')
    })

    it('has menu with attendance-industry-dashboard', () => {
      expect(buildSunbirdClientModStub().menu?.[0]?.id).toBe('attendance-industry-dashboard')
    })

    it('has frontend pro_entry_path /attendance-industry/dashboard', () => {
      expect(buildSunbirdClientModStub().frontend?.pro_entry_path).toBe('/attendance-industry/dashboard')
    })

    it('does not override the customer industry shell', () => {
      expect(buildSunbirdClientModStub().menu_overrides).toEqual([])
    })
  })

  describe('buildCoatingCustomModStub', () => {
    it('returns a ModInfo with sz-qsm-pro id', () => {
      expect(buildCoatingCustomModStub().id).toBe('sz-qsm-pro')
    })

    it('has name 奇士美 PRO', () => {
      expect(buildCoatingCustomModStub().name).toBe('奇士美 PRO')
    })

    it('has primary set to true', () => {
      expect(buildCoatingCustomModStub().primary).toBe(true)
    })

    it('has industry id 涂料', () => {
      expect(buildCoatingCustomModStub().industry?.id).toBe('涂料')
    })

    it('has menu with qsm-pro-home', () => {
      expect(buildCoatingCustomModStub().menu?.[0]?.id).toBe('qsm-pro-home')
    })

    it('has frontend pro_entry_path /qsm-pro', () => {
      expect(buildCoatingCustomModStub().frontend?.pro_entry_path).toBe('/qsm-pro')
    })

    it('has menu_overrides copied from COATING_CUSTOM_MOD_FALLBACK_OVERRIDES', () => {
      const stub = buildCoatingCustomModStub()
      expect(stub.menu_overrides?.length).toBe(COATING_CUSTOM_MOD_FALLBACK_OVERRIDES.length)
    })

    it('returns new menu_overrides array each call (not shared reference)', () => {
      const stub1 = buildCoatingCustomModStub()
      const stub2 = buildCoatingCustomModStub()
      expect(stub1.menu_overrides).not.toBe(stub2.menu_overrides)
    })
  })
})

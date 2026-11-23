import { describe, it, expect } from 'vitest'
import {
  ADMIN_OPERATOR_MENU_ITEMS,
  ADMIN_OPERATOR_AUX_MENU_ITEMS,
  ADMIN_SIDEBAR_PINNED_TOP_KEYS,
  ADMIN_OPERATOR_VISIBLE_CORE_KEYS,
  ADMIN_OPERATOR_CORE_KEYS,
  ADMIN_OPERATOR_HOME_ROUTE,
  ADMIN_OPERATOR_BRAND_TITLE,
  ADMIN_OPERATOR_BRAND_SUBTITLE,
  ADMIN_OPERATOR_ROUTE_NAMES,
  ADMIN_OPERATOR_HIDDEN_MOD_IDS,
  ADMIN_OPERATOR_ATTENDANCE_MOD_IDS,
  ADMIN_OPERATOR_ERP_MOD_MENU_ALLOWLIST,
  ADMIN_OPERATOR_HIDDEN_HOST_KEYS,
  ADMIN_OPERATOR_BLOCKED_ROUTE_NAMES,
  isAdminOperatorNavContext,
} from './adminOperatorNav'

describe('adminOperatorNav constants and functions', () => {
  describe('ADMIN_OPERATOR_MENU_ITEMS', () => {
    it('is an empty array', () => {
      expect(ADMIN_OPERATOR_MENU_ITEMS).toEqual([])
    })
  })

  describe('ADMIN_OPERATOR_AUX_MENU_ITEMS', () => {
    it('is an empty array', () => {
      expect(ADMIN_OPERATOR_AUX_MENU_ITEMS).toEqual([])
    })
  })

  describe('ADMIN_SIDEBAR_PINNED_TOP_KEYS', () => {
    it('is an empty array', () => {
      expect(ADMIN_SIDEBAR_PINNED_TOP_KEYS).toEqual([])
    })
  })

  describe('ADMIN_OPERATOR_VISIBLE_CORE_KEYS', () => {
    it('is a Set', () => {
      expect(ADMIN_OPERATOR_VISIBLE_CORE_KEYS).toBeInstanceOf(Set)
    })

    it('is empty', () => {
      expect(ADMIN_OPERATOR_VISIBLE_CORE_KEYS.size).toBe(0)
    })
  })

  describe('ADMIN_OPERATOR_CORE_KEYS', () => {
    it('is the same as ADMIN_OPERATOR_VISIBLE_CORE_KEYS', () => {
      expect(ADMIN_OPERATOR_CORE_KEYS).toBe(ADMIN_OPERATOR_VISIBLE_CORE_KEYS)
    })
  })

  describe('ADMIN_OPERATOR_HOME_ROUTE', () => {
    it('is chat', () => {
      expect(ADMIN_OPERATOR_HOME_ROUTE).toBe('chat')
    })
  })

  describe('ADMIN_OPERATOR_BRAND_TITLE', () => {
    it('is XCMAX', () => {
      expect(ADMIN_OPERATOR_BRAND_TITLE).toBe('XCMAX')
    })
  })

  describe('ADMIN_OPERATOR_BRAND_SUBTITLE', () => {
    it('is empty string', () => {
      expect(ADMIN_OPERATOR_BRAND_SUBTITLE).toBe('')
    })
  })

  describe('ADMIN_OPERATOR_ROUTE_NAMES', () => {
    it('is a Set', () => {
      expect(ADMIN_OPERATOR_ROUTE_NAMES).toBeInstanceOf(Set)
    })

    it('contains login', () => {
      expect(ADMIN_OPERATOR_ROUTE_NAMES.has('login')).toBe(true)
    })

    it('contains chat', () => {
      expect(ADMIN_OPERATOR_ROUTE_NAMES.has('chat')).toBe(true)
    })

    it('contains lan-gate', () => {
      expect(ADMIN_OPERATOR_ROUTE_NAMES.has('lan-gate')).toBe(true)
    })

    it('does not contain unknown route', () => {
      expect(ADMIN_OPERATOR_ROUTE_NAMES.has('unknown')).toBe(false)
    })
  })

  describe('ADMIN_OPERATOR_HIDDEN_MOD_IDS', () => {
    it('is an empty Set', () => {
      expect(ADMIN_OPERATOR_HIDDEN_MOD_IDS.size).toBe(0)
    })
  })

  describe('ADMIN_OPERATOR_ATTENDANCE_MOD_IDS', () => {
    it('is an empty Set', () => {
      expect(ADMIN_OPERATOR_ATTENDANCE_MOD_IDS.size).toBe(0)
    })
  })

  describe('ADMIN_OPERATOR_ERP_MOD_MENU_ALLOWLIST', () => {
    it('is an empty Set', () => {
      expect(ADMIN_OPERATOR_ERP_MOD_MENU_ALLOWLIST.size).toBe(0)
    })
  })

  describe('ADMIN_OPERATOR_HIDDEN_HOST_KEYS', () => {
    it('is an empty Set', () => {
      expect(ADMIN_OPERATOR_HIDDEN_HOST_KEYS.size).toBe(0)
    })
  })

  describe('ADMIN_OPERATOR_BLOCKED_ROUTE_NAMES', () => {
    it('is an empty Set', () => {
      expect(ADMIN_OPERATOR_BLOCKED_ROUTE_NAMES.size).toBe(0)
    })
  })

  describe('isAdminOperatorNavContext', () => {
    it('always returns false for any view and non-admin', () => {
      expect(isAdminOperatorNavContext('chat', false)).toBe(false)
    })

    it('always returns false for any view and admin', () => {
      expect(isAdminOperatorNavContext('chat', true)).toBe(false)
    })

    it('returns false for empty view', () => {
      expect(isAdminOperatorNavContext('', false)).toBe(false)
    })

    it('returns false for unknown view', () => {
      expect(isAdminOperatorNavContext('unknown', true)).toBe(false)
    })
  })
})

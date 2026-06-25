import { describe, it, expect, beforeEach } from 'vitest'
import {
  APPROVAL_BRIDGE_MOD_ID,
  LS_APPROVAL_MOD_FACADE_ENABLED,
  readApprovalModFacadeEnabled,
  setApprovalModFacadeEnabled,
} from './approvalMod'

describe('approvalMod constants and functions', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('APPROVAL_BRIDGE_MOD_ID', () => {
    it('is the approval bridge mod id', () => {
      expect(APPROVAL_BRIDGE_MOD_ID).toBe('xcagi-approval-bridge')
    })
  })

  describe('LS_APPROVAL_MOD_FACADE_ENABLED', () => {
    it('is the localStorage key string', () => {
      expect(LS_APPROVAL_MOD_FACADE_ENABLED).toBe('xcagi_approval_mod_facade_enabled')
    })
  })

  describe('readApprovalModFacadeEnabled', () => {
    it('returns false when localStorage is empty', () => {
      expect(readApprovalModFacadeEnabled()).toBe(false)
    })

    it('returns false when value is not 1', () => {
      localStorage.setItem(LS_APPROVAL_MOD_FACADE_ENABLED, '0')
      expect(readApprovalModFacadeEnabled()).toBe(false)
    })

    it('returns true when value is 1', () => {
      localStorage.setItem(LS_APPROVAL_MOD_FACADE_ENABLED, '1')
      expect(readApprovalModFacadeEnabled()).toBe(true)
    })

    it('returns false for arbitrary string value', () => {
      localStorage.setItem(LS_APPROVAL_MOD_FACADE_ENABLED, 'true')
      expect(readApprovalModFacadeEnabled()).toBe(false)
    })
  })

  describe('setApprovalModFacadeEnabled', () => {
    it('sets value to 1 when true', () => {
      setApprovalModFacadeEnabled(true)
      expect(localStorage.getItem(LS_APPROVAL_MOD_FACADE_ENABLED)).toBe('1')
    })

    it('sets value to 0 when false', () => {
      setApprovalModFacadeEnabled(false)
      expect(localStorage.getItem(LS_APPROVAL_MOD_FACADE_ENABLED)).toBe('0')
    })

    it('overwrites previous value', () => {
      setApprovalModFacadeEnabled(true)
      setApprovalModFacadeEnabled(false)
      expect(localStorage.getItem(LS_APPROVAL_MOD_FACADE_ENABLED)).toBe('0')
    })

    it('can toggle from false to true', () => {
      setApprovalModFacadeEnabled(false)
      expect(readApprovalModFacadeEnabled()).toBe(false)
      setApprovalModFacadeEnabled(true)
      expect(readApprovalModFacadeEnabled()).toBe(true)
    })
  })
})

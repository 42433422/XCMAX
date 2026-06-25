import { describe, it, expect, beforeEach } from 'vitest'
import {
  ERP_DOMAIN_BRIDGE_MOD_ID,
  LS_ERP_DOMAIN_MOD_FACADE_ENABLED,
  LEGACY_CLIENT_ERP_MOD_ID,
  readErpDomainModFacadeEnabled,
  setErpDomainModFacadeEnabled,
} from './erpDomainMod'

describe('erpDomainMod constants and functions', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('ERP_DOMAIN_BRIDGE_MOD_ID', () => {
    it('is the erp domain bridge mod id', () => {
      expect(ERP_DOMAIN_BRIDGE_MOD_ID).toBe('xcagi-erp-domain-bridge')
    })
  })

  describe('LEGACY_CLIENT_ERP_MOD_ID', () => {
    it('is the taiyangniao-pro mod id', () => {
      expect(LEGACY_CLIENT_ERP_MOD_ID).toBe('taiyangniao-pro')
    })
  })

  describe('LS_ERP_DOMAIN_MOD_FACADE_ENABLED', () => {
    it('is the localStorage key string', () => {
      expect(LS_ERP_DOMAIN_MOD_FACADE_ENABLED).toBe('xcagi_erp_domain_mod_facade_enabled')
    })
  })

  describe('readErpDomainModFacadeEnabled', () => {
    it('returns false when localStorage is empty', () => {
      expect(readErpDomainModFacadeEnabled()).toBe(false)
    })

    it('returns false when value is 0', () => {
      localStorage.setItem(LS_ERP_DOMAIN_MOD_FACADE_ENABLED, '0')
      expect(readErpDomainModFacadeEnabled()).toBe(false)
    })

    it('returns true when value is 1', () => {
      localStorage.setItem(LS_ERP_DOMAIN_MOD_FACADE_ENABLED, '1')
      expect(readErpDomainModFacadeEnabled()).toBe(true)
    })

    it('returns false for arbitrary string', () => {
      localStorage.setItem(LS_ERP_DOMAIN_MOD_FACADE_ENABLED, 'enabled')
      expect(readErpDomainModFacadeEnabled()).toBe(false)
    })
  })

  describe('setErpDomainModFacadeEnabled', () => {
    it('sets value to 1 when true', () => {
      setErpDomainModFacadeEnabled(true)
      expect(localStorage.getItem(LS_ERP_DOMAIN_MOD_FACADE_ENABLED)).toBe('1')
    })

    it('sets value to 0 when false', () => {
      setErpDomainModFacadeEnabled(false)
      expect(localStorage.getItem(LS_ERP_DOMAIN_MOD_FACADE_ENABLED)).toBe('0')
    })

    it('read reflects write', () => {
      setErpDomainModFacadeEnabled(true)
      expect(readErpDomainModFacadeEnabled()).toBe(true)
      setErpDomainModFacadeEnabled(false)
      expect(readErpDomainModFacadeEnabled()).toBe(false)
    })
  })
})

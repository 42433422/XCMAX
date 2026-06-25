import { describe, it, expect, beforeEach } from 'vitest'
import {
  CUSTOMER_SERVICE_BRIDGE_MOD_ID,
  LS_CUSTOMER_SERVICE_MOD_PAGES_ENABLED,
  readCustomerServiceModPagesEnabled,
  customerServiceModFrontendRoutesAvailable,
  setCustomerServiceModPagesEnabled,
} from './customerServiceMod'

describe('customerServiceMod constants and functions', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('CUSTOMER_SERVICE_BRIDGE_MOD_ID', () => {
    it('is the customer service bridge mod id', () => {
      expect(CUSTOMER_SERVICE_BRIDGE_MOD_ID).toBe('xcagi-customer-service-bridge')
    })
  })

  describe('LS_CUSTOMER_SERVICE_MOD_PAGES_ENABLED', () => {
    it('is the localStorage key string', () => {
      expect(LS_CUSTOMER_SERVICE_MOD_PAGES_ENABLED).toBe('xcagi_customer_service_mod_pages_enabled')
    })
  })

  describe('readCustomerServiceModPagesEnabled', () => {
    it('returns false when localStorage is empty', () => {
      expect(readCustomerServiceModPagesEnabled()).toBe(false)
    })

    it('returns false when value is 0', () => {
      localStorage.setItem(LS_CUSTOMER_SERVICE_MOD_PAGES_ENABLED, '0')
      expect(readCustomerServiceModPagesEnabled()).toBe(false)
    })

    it('returns true when value is 1', () => {
      localStorage.setItem(LS_CUSTOMER_SERVICE_MOD_PAGES_ENABLED, '1')
      expect(readCustomerServiceModPagesEnabled()).toBe(true)
    })

    it('returns false for arbitrary string', () => {
      localStorage.setItem(LS_CUSTOMER_SERVICE_MOD_PAGES_ENABLED, 'enabled')
      expect(readCustomerServiceModPagesEnabled()).toBe(false)
    })
  })

  describe('setCustomerServiceModPagesEnabled', () => {
    it('sets value to 1 when true', () => {
      setCustomerServiceModPagesEnabled(true)
      expect(localStorage.getItem(LS_CUSTOMER_SERVICE_MOD_PAGES_ENABLED)).toBe('1')
    })

    it('sets value to 0 when false', () => {
      setCustomerServiceModPagesEnabled(false)
      expect(localStorage.getItem(LS_CUSTOMER_SERVICE_MOD_PAGES_ENABLED)).toBe('0')
    })

    it('read reflects write', () => {
      setCustomerServiceModPagesEnabled(true)
      expect(readCustomerServiceModPagesEnabled()).toBe(true)
      setCustomerServiceModPagesEnabled(false)
      expect(readCustomerServiceModPagesEnabled()).toBe(false)
    })
  })

  describe('customerServiceModFrontendRoutesAvailable', () => {
    it('always returns true', () => {
      expect(customerServiceModFrontendRoutesAvailable()).toBe(true)
    })
  })
})

import { describe, it, expect } from 'vitest'
import {
  ENTERPRISE_CUSTOMER_SERVICE_KEY,
  INTERNAL_CUSTOMER_SERVICE_KEY,
  customerServiceSideForNavKey,
  isCustomerServiceNavVisible,
} from './customerServiceNav'

describe('customerServiceNav constants and functions', () => {
  describe('ENTERPRISE_CUSTOMER_SERVICE_KEY', () => {
    it('is the enterprise customer service key', () => {
      expect(ENTERPRISE_CUSTOMER_SERVICE_KEY).toBe('enterprise-customer-service')
    })
  })

  describe('INTERNAL_CUSTOMER_SERVICE_KEY', () => {
    it('is the internal customer service key', () => {
      expect(INTERNAL_CUSTOMER_SERVICE_KEY).toBe('internal-customer-service')
    })
  })

  describe('customerServiceSideForNavKey', () => {
    it('returns enterprise for enterprise key', () => {
      expect(customerServiceSideForNavKey('enterprise-customer-service')).toBe('enterprise')
    })

    it('returns admin for internal key', () => {
      expect(customerServiceSideForNavKey('internal-customer-service')).toBe('admin')
    })

    it('returns null for unknown key', () => {
      expect(customerServiceSideForNavKey('unknown-key')).toBeNull()
    })

    it('returns null for empty string', () => {
      expect(customerServiceSideForNavKey('')).toBeNull()
    })

    it('returns null for non-customer-service key', () => {
      expect(customerServiceSideForNavKey('chat')).toBeNull()
    })
  })

  describe('isCustomerServiceNavVisible', () => {
    it('returns true for enterprise key when not admin', () => {
      expect(isCustomerServiceNavVisible('enterprise-customer-service', false)).toBe(true)
    })

    it('returns false for enterprise key when admin', () => {
      expect(isCustomerServiceNavVisible('enterprise-customer-service', true)).toBe(false)
    })

    it('returns true for internal key when admin', () => {
      expect(isCustomerServiceNavVisible('internal-customer-service', true)).toBe(true)
    })

    it('returns false for internal key when not admin', () => {
      expect(isCustomerServiceNavVisible('internal-customer-service', false)).toBe(false)
    })

    it('returns true for unknown key regardless of admin status', () => {
      expect(isCustomerServiceNavVisible('unknown-key', false)).toBe(true)
      expect(isCustomerServiceNavVisible('unknown-key', true)).toBe(true)
    })

    it('returns true for empty key regardless of admin status', () => {
      expect(isCustomerServiceNavVisible('', false)).toBe(true)
      expect(isCustomerServiceNavVisible('', true)).toBe(true)
    })
  })
})

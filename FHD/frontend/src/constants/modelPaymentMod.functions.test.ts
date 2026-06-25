import { describe, it, expect, beforeEach } from 'vitest'
import {
  MODEL_PAYMENT_BRIDGE_MOD_ID,
  LS_MODEL_PAYMENT_MOD_FACADE_ENABLED,
  readModelPaymentModFacadeEnabled,
  setModelPaymentModFacadeEnabled,
} from './modelPaymentMod'

describe('modelPaymentMod constants and functions', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('MODEL_PAYMENT_BRIDGE_MOD_ID', () => {
    it('is the model payment bridge mod id', () => {
      expect(MODEL_PAYMENT_BRIDGE_MOD_ID).toBe('xcagi-model-payment-bridge')
    })
  })

  describe('LS_MODEL_PAYMENT_MOD_FACADE_ENABLED', () => {
    it('is the localStorage key string', () => {
      expect(LS_MODEL_PAYMENT_MOD_FACADE_ENABLED).toBe('xcagi_model_payment_mod_facade_enabled')
    })
  })

  describe('readModelPaymentModFacadeEnabled', () => {
    it('returns false when localStorage is empty', () => {
      expect(readModelPaymentModFacadeEnabled()).toBe(false)
    })

    it('returns false when value is 0', () => {
      localStorage.setItem(LS_MODEL_PAYMENT_MOD_FACADE_ENABLED, '0')
      expect(readModelPaymentModFacadeEnabled()).toBe(false)
    })

    it('returns true when value is 1', () => {
      localStorage.setItem(LS_MODEL_PAYMENT_MOD_FACADE_ENABLED, '1')
      expect(readModelPaymentModFacadeEnabled()).toBe(true)
    })

    it('returns false for arbitrary string', () => {
      localStorage.setItem(LS_MODEL_PAYMENT_MOD_FACADE_ENABLED, 'on')
      expect(readModelPaymentModFacadeEnabled()).toBe(false)
    })
  })

  describe('setModelPaymentModFacadeEnabled', () => {
    it('sets value to 1 when true', () => {
      setModelPaymentModFacadeEnabled(true)
      expect(localStorage.getItem(LS_MODEL_PAYMENT_MOD_FACADE_ENABLED)).toBe('1')
    })

    it('sets value to 0 when false', () => {
      setModelPaymentModFacadeEnabled(false)
      expect(localStorage.getItem(LS_MODEL_PAYMENT_MOD_FACADE_ENABLED)).toBe('0')
    })

    it('read reflects write', () => {
      setModelPaymentModFacadeEnabled(true)
      expect(readModelPaymentModFacadeEnabled()).toBe(true)
      setModelPaymentModFacadeEnabled(false)
      expect(readModelPaymentModFacadeEnabled()).toBe(false)
    })
  })
})

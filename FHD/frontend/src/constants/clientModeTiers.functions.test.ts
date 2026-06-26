import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  isClientModeTiersUiEnabled,
  resetClientModeTierLocalState,
  CLIENT_MODE_TIERS_UI_ENABLED,
  PRO_INTENT_EXPERIENCE_KEY,
} from './clientModeTiers'

describe('clientModeTiers', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('CLIENT_MODE_TIERS_UI_ENABLED', () => {
    it('is a boolean constant', () => {
      expect(typeof CLIENT_MODE_TIERS_UI_ENABLED).toBe('boolean')
    })
  })

  describe('PRO_INTENT_EXPERIENCE_KEY', () => {
    it('is the expected string constant', () => {
      expect(PRO_INTENT_EXPERIENCE_KEY).toBe('xcagi_pro_intent_experience')
    })
  })

  describe('isClientModeTiersUiEnabled', () => {
    it('returns the value of CLIENT_MODE_TIERS_UI_ENABLED', () => {
      expect(isClientModeTiersUiEnabled()).toBe(CLIENT_MODE_TIERS_UI_ENABLED)
    })

    it('returns false (current configured value)', () => {
      expect(isClientModeTiersUiEnabled()).toBe(false)
    })
  })

  describe('resetClientModeTierLocalState', () => {
    it('sets localStorage item to "0"', () => {
      resetClientModeTierLocalState()
      expect(localStorage.getItem(PRO_INTENT_EXPERIENCE_KEY)).toBe('0')
    })

    it('does not throw when localStorage is available', () => {
      expect(() => resetClientModeTierLocalState()).not.toThrow()
    })

    it('does not throw when localStorage.setItem throws', () => {
      const origSetItem = Storage.prototype.setItem
      Storage.prototype.setItem = () => {
        throw new Error('unavailable')
      }
      try {
        expect(() => resetClientModeTierLocalState()).not.toThrow()
      } finally {
        Storage.prototype.setItem = origSetItem
      }
    })

    it('overwrites existing value', () => {
      localStorage.setItem(PRO_INTENT_EXPERIENCE_KEY, '1')
      resetClientModeTierLocalState()
      expect(localStorage.getItem(PRO_INTENT_EXPERIENCE_KEY)).toBe('0')
    })
  })
})

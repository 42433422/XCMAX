import { describe, it, expect, beforeEach } from 'vitest'
import {
  LAN_BRIDGE_MOD_ID,
  LS_LAN_MOD_FACADE_ENABLED,
  readLanModFacadeEnabled,
  setLanModFacadeEnabled,
} from './lanMod'

describe('lanMod constants and functions', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('LAN_BRIDGE_MOD_ID', () => {
    it('is the lan license bridge mod id', () => {
      expect(LAN_BRIDGE_MOD_ID).toBe('xcagi-lan-license-bridge')
    })
  })

  describe('LS_LAN_MOD_FACADE_ENABLED', () => {
    it('is the localStorage key string', () => {
      expect(LS_LAN_MOD_FACADE_ENABLED).toBe('xcagi_lan_mod_facade_enabled')
    })
  })

  describe('readLanModFacadeEnabled', () => {
    it('returns false when localStorage is empty', () => {
      expect(readLanModFacadeEnabled()).toBe(false)
    })

    it('returns false when value is 0', () => {
      localStorage.setItem(LS_LAN_MOD_FACADE_ENABLED, '0')
      expect(readLanModFacadeEnabled()).toBe(false)
    })

    it('returns true when value is 1', () => {
      localStorage.setItem(LS_LAN_MOD_FACADE_ENABLED, '1')
      expect(readLanModFacadeEnabled()).toBe(true)
    })

    it('returns false for non-1 string', () => {
      localStorage.setItem(LS_LAN_MOD_FACADE_ENABLED, 'yes')
      expect(readLanModFacadeEnabled()).toBe(false)
    })
  })

  describe('setLanModFacadeEnabled', () => {
    it('sets value to 1 when true', () => {
      setLanModFacadeEnabled(true)
      expect(localStorage.getItem(LS_LAN_MOD_FACADE_ENABLED)).toBe('1')
    })

    it('sets value to 0 when false', () => {
      setLanModFacadeEnabled(false)
      expect(localStorage.getItem(LS_LAN_MOD_FACADE_ENABLED)).toBe('0')
    })

    it('overwrites previous value when toggling', () => {
      setLanModFacadeEnabled(true)
      setLanModFacadeEnabled(false)
      setLanModFacadeEnabled(true)
      expect(localStorage.getItem(LS_LAN_MOD_FACADE_ENABLED)).toBe('1')
    })

    it('read reflects write', () => {
      setLanModFacadeEnabled(true)
      expect(readLanModFacadeEnabled()).toBe(true)
      setLanModFacadeEnabled(false)
      expect(readLanModFacadeEnabled()).toBe(false)
    })
  })
})

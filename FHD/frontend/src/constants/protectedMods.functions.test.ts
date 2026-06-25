import { describe, it, expect } from 'vitest'
import {
  PROTECTED_CLIENT_MOD_IDS,
  isProtectedClientModId,
  type ProtectedClientModId,
} from './protectedMods'

describe('protectedMods constants and functions', () => {
  describe('PROTECTED_CLIENT_MOD_IDS', () => {
    it('is a non-empty readonly array', () => {
      expect(Array.isArray(PROTECTED_CLIENT_MOD_IDS)).toBe(true)
      expect(PROTECTED_CLIENT_MOD_IDS.length).toBeGreaterThan(0)
    })

    it('contains known protected mod ids', () => {
      expect(PROTECTED_CLIENT_MOD_IDS).toContain('attendance-industry')
      expect(PROTECTED_CLIENT_MOD_IDS).toContain('coating-industry')
      expect(PROTECTED_CLIENT_MOD_IDS).toContain('taiyangniao-pro')
      expect(PROTECTED_CLIENT_MOD_IDS).toContain('sz-qsm-pro')
    })
  })

  describe('isProtectedClientModId', () => {
    it('returns true for known protected mod id', () => {
      expect(isProtectedClientModId('attendance-industry')).toBe(true)
    })

    it('returns true for coating-industry', () => {
      expect(isProtectedClientModId('coating-industry')).toBe(true)
    })

    it('returns true for taiyangniao-pro', () => {
      expect(isProtectedClientModId('taiyangniao-pro')).toBe(true)
    })

    it('returns true for sz-qsm-pro', () => {
      expect(isProtectedClientModId('sz-qsm-pro')).toBe(true)
    })

    it('returns false for unknown mod id', () => {
      expect(isProtectedClientModId('unknown-mod')).toBe(false)
    })

    it('returns false for empty string', () => {
      expect(isProtectedClientModId('')).toBe(false)
    })

    it('trims whitespace before checking', () => {
      expect(isProtectedClientModId('  attendance-industry  ')).toBe(true)
    })

    it('returns false for null input', () => {
      expect(isProtectedClientModId(null as unknown as string)).toBe(false)
    })

    it('returns false for undefined input', () => {
      expect(isProtectedClientModId(undefined as unknown as string)).toBe(false)
    })

    it('is case-sensitive', () => {
      expect(isProtectedClientModId('ATTENDANCE-INDUSTRY')).toBe(false)
    })
  })

  describe('ProtectedClientModId type', () => {
    it('can be assigned a known id', () => {
      const id: ProtectedClientModId = 'attendance-industry'
      expect(id).toBe('attendance-industry')
    })
  })
})

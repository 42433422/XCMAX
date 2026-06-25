import { describe, it, expect } from 'vitest'
import {
  SUNBIRD_CLIENT_MOD_ID,
  isSunbirdAccountUsername,
  augmentEntitledModIdsForAccount,
  preferredClientModIdForAccount,
  shouldBindClientPrimaryErpMod,
} from './accountModBinding'

describe('accountModBinding constants and functions', () => {
  describe('SUNBIRD_CLIENT_MOD_ID', () => {
    it('is the taiyangniao-pro mod id', () => {
      expect(SUNBIRD_CLIENT_MOD_ID).toBe('taiyangniao-pro')
    })
  })

  describe('isSunbirdAccountUsername', () => {
    it('returns true for sunbird (lowercase)', () => {
      expect(isSunbirdAccountUsername('sunbird')).toBe(true)
    })

    it('returns true for SUNBIRD (uppercase)', () => {
      expect(isSunbirdAccountUsername('SUNBIRD')).toBe(true)
    })

    it('returns true for Sunbird (mixed case)', () => {
      expect(isSunbirdAccountUsername('Sunbird')).toBe(true)
    })

    it('returns false for unknown username', () => {
      expect(isSunbirdAccountUsername('other-user')).toBe(false)
    })

    it('returns false for empty string', () => {
      expect(isSunbirdAccountUsername('')).toBe(false)
    })

    it('returns false for null input', () => {
      expect(isSunbirdAccountUsername(null)).toBe(false)
    })

    it('returns false for undefined input', () => {
      expect(isSunbirdAccountUsername(undefined)).toBe(false)
    })

    it('trims whitespace before checking', () => {
      expect(isSunbirdAccountUsername('  sunbird  ')).toBe(true)
    })

    it('returns false for whitespace-only string', () => {
      expect(isSunbirdAccountUsername('   ')).toBe(false)
    })
  })

  describe('augmentEntitledModIdsForAccount', () => {
    it('returns the same list for normal input', () => {
      const result = augmentEntitledModIdsForAccount('user', ['mod-a', 'mod-b'])
      expect(result).toEqual(['mod-a', 'mod-b'])
    })

    it('deduplicates mod ids', () => {
      const result = augmentEntitledModIdsForAccount('user', ['mod-a', 'mod-b', 'mod-a'])
      expect(result).toEqual(['mod-a', 'mod-b'])
    })

    it('trims whitespace from mod ids', () => {
      const result = augmentEntitledModIdsForAccount('user', ['  mod-a  ', 'mod-b'])
      expect(result).toEqual(['mod-a', 'mod-b'])
    })

    it('skips empty mod ids', () => {
      const result = augmentEntitledModIdsForAccount('user', ['mod-a', '', '  ', 'mod-b'])
      expect(result).toEqual(['mod-a', 'mod-b'])
    })

    it('returns empty array for undefined input', () => {
      const result = augmentEntitledModIdsForAccount('user', undefined)
      expect(result).toEqual([])
    })

    it('returns empty array for null input', () => {
      const result = augmentEntitledModIdsForAccount('user', null as unknown as string[])
      expect(result).toEqual([])
    })

    it('returns empty array for empty array input', () => {
      const result = augmentEntitledModIdsForAccount('user', [])
      expect(result).toEqual([])
    })

    it('works with null username', () => {
      const result = augmentEntitledModIdsForAccount(null, ['mod-a'])
      expect(result).toEqual(['mod-a'])
    })
  })

  describe('preferredClientModIdForAccount', () => {
    it('returns empty string for any username', () => {
      expect(preferredClientModIdForAccount('sunbird')).toBe('')
    })

    it('returns empty string for null username', () => {
      expect(preferredClientModIdForAccount(null)).toBe('')
    })

    it('returns empty string for undefined username', () => {
      expect(preferredClientModIdForAccount(undefined)).toBe('')
    })

    it('returns empty string for empty username', () => {
      expect(preferredClientModIdForAccount('')).toBe('')
    })
  })

  describe('shouldBindClientPrimaryErpMod', () => {
    it('returns false for normal username', () => {
      expect(shouldBindClientPrimaryErpMod('user')).toBe(false)
    })

    it('returns false for sunbird username', () => {
      expect(shouldBindClientPrimaryErpMod('sunbird')).toBe(false)
    })

    it('returns false for null username', () => {
      expect(shouldBindClientPrimaryErpMod(null)).toBe(false)
    })

    it('returns false for undefined username', () => {
      expect(shouldBindClientPrimaryErpMod(undefined)).toBe(false)
    })

    it('returns false even when isAdminAccount is true', () => {
      expect(shouldBindClientPrimaryErpMod('user', { isAdminAccount: true })).toBe(false)
    })

    it('returns false when options is undefined', () => {
      expect(shouldBindClientPrimaryErpMod('user', undefined)).toBe(false)
    })
  })
})

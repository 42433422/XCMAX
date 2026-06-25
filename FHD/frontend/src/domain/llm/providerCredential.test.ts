import { describe, it, expect } from 'vitest'
import {
  providerRowHasUsableKey,
  buildProviderStatusMap,
  type LlmProviderStatus,
} from './providerCredential'

describe('providerCredential', () => {
  describe('providerRowHasUsableKey', () => {
    it('returns false for undefined row', () => {
      expect(providerRowHasUsableKey(undefined, false)).toBe(false)
    })

    it('returns false for null row', () => {
      expect(providerRowHasUsableKey(null, false)).toBe(false)
    })

    it('returns true when has_platform_key is true', () => {
      const row: LlmProviderStatus = { provider: 'openai', has_platform_key: true }
      expect(providerRowHasUsableKey(row, false)).toBe(true)
    })

    it('returns true when has_platform_key is true regardless of fernet', () => {
      const row: LlmProviderStatus = { provider: 'openai', has_platform_key: true }
      expect(providerRowHasUsableKey(row, false)).toBe(true)
      expect(providerRowHasUsableKey(row, true)).toBe(true)
    })

    it('returns true when has_user_override is true and fernetConfigured is true', () => {
      const row: LlmProviderStatus = {
        provider: 'openai',
        has_user_override: true,
      }
      expect(providerRowHasUsableKey(row, true)).toBe(true)
    })

    it('returns false when has_user_override is true but fernetConfigured is false', () => {
      const row: LlmProviderStatus = {
        provider: 'openai',
        has_user_override: true,
      }
      expect(providerRowHasUsableKey(row, false)).toBe(false)
    })

    it('returns false when neither has_platform_key nor has_user_override', () => {
      const row: LlmProviderStatus = { provider: 'openai' }
      expect(providerRowHasUsableKey(row, false)).toBe(false)
      expect(providerRowHasUsableKey(row, true)).toBe(false)
    })

    it('returns false when both keys are false', () => {
      const row: LlmProviderStatus = {
        provider: 'openai',
        has_platform_key: false,
        has_user_override: false,
      }
      expect(providerRowHasUsableKey(row, true)).toBe(false)
    })

    it('platform key takes precedence over user override', () => {
      const row: LlmProviderStatus = {
        provider: 'openai',
        has_platform_key: true,
        has_user_override: false,
      }
      expect(providerRowHasUsableKey(row, false)).toBe(true)
    })

    it('handles empty row object', () => {
      const row: LlmProviderStatus = { provider: 'openai' }
      expect(providerRowHasUsableKey(row, true)).toBe(false)
    })
  })

  describe('buildProviderStatusMap', () => {
    it('returns empty object for undefined rows', () => {
      expect(buildProviderStatusMap(undefined)).toEqual({})
    })

    it('returns empty object for null rows', () => {
      expect(buildProviderStatusMap(null)).toEqual({})
    })

    it('returns empty object for empty array', () => {
      expect(buildProviderStatusMap([])).toEqual({})
    })

    it('builds map keyed by provider id', () => {
      const rows: LlmProviderStatus[] = [
        { provider: 'openai', has_platform_key: true },
        { provider: 'anthropic', has_user_override: true },
      ]
      const map = buildProviderStatusMap(rows)
      expect(map.openai).toEqual({ provider: 'openai', has_platform_key: true })
      expect(map.anthropic).toEqual({
        provider: 'anthropic',
        has_user_override: true,
      })
    })

    it('skips rows with empty provider', () => {
      const rows: LlmProviderStatus[] = [
        { provider: '', has_platform_key: true },
        { provider: 'openai', has_platform_key: true },
      ]
      const map = buildProviderStatusMap(rows)
      expect(Object.keys(map)).toHaveLength(1)
      expect(map.openai).toBeDefined()
    })

    it('skips rows with whitespace-only provider', () => {
      const rows: LlmProviderStatus[] = [
        { provider: '   ', has_platform_key: true },
        { provider: 'openai', has_platform_key: true },
      ]
      const map = buildProviderStatusMap(rows)
      expect(Object.keys(map)).toHaveLength(1)
    })

    it('skips rows with undefined provider', () => {
      const rows: LlmProviderStatus[] = [
        { provider: undefined as unknown as string, has_platform_key: true },
        { provider: 'openai', has_platform_key: true },
      ]
      const map = buildProviderStatusMap(rows)
      expect(Object.keys(map)).toHaveLength(1)
    })

    it('trims provider id', () => {
      const rows: LlmProviderStatus[] = [
        { provider: '  openai  ', has_platform_key: true },
      ]
      const map = buildProviderStatusMap(rows)
      expect(map.openai).toBeDefined()
      expect(map['  openai  ']).toBeUndefined()
    })

    it('later rows overwrite earlier rows with same provider', () => {
      const rows: LlmProviderStatus[] = [
        { provider: 'openai', has_platform_key: true },
        { provider: 'openai', has_user_override: true },
      ]
      const map = buildProviderStatusMap(rows)
      expect(map.openai.has_user_override).toBe(true)
      expect(map.openai.has_platform_key).toBeUndefined()
    })

    it('handles rows with extra fields', () => {
      const rows: LlmProviderStatus[] = [
        {
          provider: 'openai',
          label: 'OpenAI',
          masked_key: 'sk-***',
          configured: true,
          healthy: true,
        },
      ]
      const map = buildProviderStatusMap(rows)
      expect(map.openai.label).toBe('OpenAI')
      expect(map.openai.masked_key).toBe('sk-***')
    })
  })
})

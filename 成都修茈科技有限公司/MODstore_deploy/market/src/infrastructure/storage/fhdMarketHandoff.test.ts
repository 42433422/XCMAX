import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  extractFhdMarketTokenFromRoute,
  fhdHandoffNeedsStrip,
  applyFhdMarketToken,
  FHD_MARKET_QUERY_KEY,
} from './fhdMarketHandoff'
import { setAuthTokens } from './tokenStore'

vi.mock('./tokenStore', () => ({
  setAuthTokens: vi.fn(),
}))

describe('fhdMarketHandoff', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('FHD_MARKET_QUERY_KEY', () => {
    it('has expected value', () => {
      expect(FHD_MARKET_QUERY_KEY).toBe('xcagi_mt')
    })
  })

  describe('extractFhdMarketTokenFromRoute', () => {
    it('extracts token from hash', () => {
      const to = { hash: '#xcagi_mt=mytoken123', query: {} } as any
      expect(extractFhdMarketTokenFromRoute(to)).toBe('mytoken123')
    })

    it('extracts token from query', () => {
      const to = { hash: '', query: { xcagi_mt: 'querytoken' } } as any
      expect(extractFhdMarketTokenFromRoute(to)).toBe('querytoken')
    })

    it('prefers hash over query', () => {
      const to = { hash: '#xcagi_mt=hashtoken', query: { xcagi_mt: 'querytoken' } } as any
      expect(extractFhdMarketTokenFromRoute(to)).toBe('hashtoken')
    })

    it('returns empty string when no token present', () => {
      const to = { hash: '', query: {} } as any
      expect(extractFhdMarketTokenFromRoute(to)).toBe('')
    })

    it('handles empty hash', () => {
      const to = { hash: '', query: {} } as any
      expect(extractFhdMarketTokenFromRoute(to)).toBe('')
    })

    it('handles hash without prefix', () => {
      const to = { hash: '#other=value', query: {} } as any
      expect(extractFhdMarketTokenFromRoute(to)).toBe('')
    })

    it('handles array query param', () => {
      const to = { hash: '', query: { xcagi_mt: ['token1', 'token2'] } } as any
      expect(extractFhdMarketTokenFromRoute(to)).toBe('token1')
    })

    it('trims whitespace from query token', () => {
      const to = { hash: '', query: { xcagi_mt: '  spaced  ' } } as any
      expect(extractFhdMarketTokenFromRoute(to)).toBe('spaced')
    })

    it('handles URL-encoded hash token', () => {
      const to = { hash: '#xcagi_mt=token%20with%20spaces', query: {} } as any
      expect(extractFhdMarketTokenFromRoute(to)).toBe('token with spaces')
    })
  })

  describe('fhdHandoffNeedsStrip', () => {
    it('returns true when hash has prefix', () => {
      const to = { hash: '#xcagi_mt=token', query: {} } as any
      expect(fhdHandoffNeedsStrip(to)).toBe(true)
    })

    it('returns true when query has key', () => {
      const to = { hash: '', query: { xcagi_mt: 'token' } } as any
      expect(fhdHandoffNeedsStrip(to)).toBe(true)
    })

    it('returns false when no token present', () => {
      const to = { hash: '', query: {} } as any
      expect(fhdHandoffNeedsStrip(to)).toBe(false)
    })

    it('returns false for unrelated hash', () => {
      const to = { hash: '#section', query: {} } as any
      expect(fhdHandoffNeedsStrip(to)).toBe(false)
    })
  })

  describe('applyFhdMarketToken', () => {
    it('calls setAuthTokens with token', () => {
      applyFhdMarketToken('my-jwt-token')
      expect(setAuthTokens).toHaveBeenCalledWith({ access_token: 'my-jwt-token' })
    })

    it('trims whitespace', () => {
      applyFhdMarketToken('  spaced-token  ')
      expect(setAuthTokens).toHaveBeenCalledWith({ access_token: 'spaced-token' })
    })

    it('does nothing for empty string', () => {
      applyFhdMarketToken('')
      expect(setAuthTokens).not.toHaveBeenCalled()
    })

    it('does nothing for whitespace-only string', () => {
      applyFhdMarketToken('   ')
      expect(setAuthTokens).not.toHaveBeenCalled()
    })
  })
})

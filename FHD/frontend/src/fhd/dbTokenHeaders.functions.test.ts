import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  LS_DB_READ_TOKEN,
  LS_DB_WRITE_TOKEN,
  LS_DB_TOKENS_BY_MOD,
  FHD_STORED_DB_TOKENS_CHANGED_EVENT,
  FHD_DB_READ_UNLOCKED_EVENT,
  FHD_DB_WRITE_UNLOCKED_EVENT,
  XCAGI_PRODUCTS_SIDEBAR_ACTIVATED,
  XCAGI_PROMPT_DB_READ_TOKEN_EVENT,
  XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT,
  fetchDbTokensStatus,
  readStoredDbTokensForMod,
  saveStoredDbTokensForMod,
  readStoredDbTokens,
  saveStoredDbTokens,
  saveStoredReadToken,
  saveStoredWriteToken,
  getProductsReadLockState,
  probeProductsReadAccess,
  urlNeedsDbReadToken,
  shouldAttachDbReadToken,
  armNextPlannerChatDbWriteToken,
  isPlannerChatDbWriteTokenArmed,
  consumePlannerChatDbWriteTokenArm,
  notifyDbReadTokenRequiredAfter403,
  notifyDbWriteTokenRequiredAfter403,
  urlNeedsDbWriteToken,
  combinedRequestUrl,
  dbReadHeaders,
  dbWriteHeaders,
  isProductsReadGateGraceActive,
  touchProductsReadGateGrace,
} from './dbTokenHeaders'

describe('dbTokenHeaders', () => {
  describe('constants', () => {
    it('exports LS_DB_READ_TOKEN', () => {
      expect(LS_DB_READ_TOKEN).toBe('xcagi_db_read_token')
    })

    it('exports LS_DB_WRITE_TOKEN', () => {
      expect(LS_DB_WRITE_TOKEN).toBe('xcagi_db_write_token')
    })

    it('exports LS_DB_TOKENS_BY_MOD', () => {
      expect(LS_DB_TOKENS_BY_MOD).toBe('xcagi_db_tokens_by_mod')
    })

    it('exports FHD_STORED_DB_TOKENS_CHANGED_EVENT', () => {
      expect(FHD_STORED_DB_TOKENS_CHANGED_EVENT).toBe('fhd:stored-db-tokens-changed')
    })

    it('exports FHD_DB_READ_UNLOCKED_EVENT', () => {
      expect(FHD_DB_READ_UNLOCKED_EVENT).toBe('fhd-db-read-unlocked')
    })

    it('exports FHD_DB_WRITE_UNLOCKED_EVENT', () => {
      expect(FHD_DB_WRITE_UNLOCKED_EVENT).toBe('fhd-db-write-unlocked')
    })

    it('exports XCAGI_PRODUCTS_SIDEBAR_ACTIVATED', () => {
      expect(XCAGI_PRODUCTS_SIDEBAR_ACTIVATED).toBe('xcagi:products-sidebar-activated')
    })

    it('exports XCAGI_PROMPT_DB_READ_TOKEN_EVENT', () => {
      expect(XCAGI_PROMPT_DB_READ_TOKEN_EVENT).toBe('xcagi:prompt-db-read-token')
    })

    it('exports XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT', () => {
      expect(XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT).toBe('xcagi:prompt-db-write-token')
    })
  })

  describe('isProductsReadGateGraceActive', () => {
    it('returns false (stub)', () => {
      expect(isProductsReadGateGraceActive()).toBe(false)
    })

    it('returns false consistently', () => {
      expect(isProductsReadGateGraceActive()).toBe(false)
      expect(isProductsReadGateGraceActive()).toBe(false)
    })
  })

  describe('touchProductsReadGateGrace', () => {
    it('does not throw (stub)', () => {
      expect(() => touchProductsReadGateGrace()).not.toThrow()
    })
  })

  describe('fetchDbTokensStatus', () => {
    it('fetches from /api/fhd/db-tokens/status with apiBase prefix', async () => {
      const mockJson = vi.fn().mockResolvedValue({ read_token_configured: true })
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
        ok: true,
        status: 200,
        json: mockJson,
      } as Response)

      const result = await fetchDbTokensStatus('https://api.example.com')

      expect(fetchSpy).toHaveBeenCalledWith('https://api.example.com/api/fhd/db-tokens/status')
      expect(result).toEqual({ read_token_configured: true })
    })

    it('uses empty apiBase by default', async () => {
      const mockJson = vi.fn().mockResolvedValue({ read_token_configured: false })
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
        ok: true,
        status: 200,
        json: mockJson,
      } as Response)

      await fetchDbTokensStatus()

      expect(fetchSpy).toHaveBeenCalledWith('/api/fhd/db-tokens/status')
    })

    it('throws when response not ok', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue({
        ok: false,
        status: 500,
        json: vi.fn(),
      } as Response)

      await expect(fetchDbTokensStatus()).rejects.toThrow('db-tokens/status 500')
    })

    it('throws with 401 status', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue({
        ok: false,
        status: 401,
        json: vi.fn(),
      } as Response)

      await expect(fetchDbTokensStatus()).rejects.toThrow('db-tokens/status 401')
    })
  })

  describe('readStoredDbTokensForMod', () => {
    it('returns empty read and write tokens (stub)', () => {
      const result = readStoredDbTokensForMod('mod1')
      expect(result).toEqual({ read: '', write: '' })
    })

    it('returns empty tokens for empty modId', () => {
      const result = readStoredDbTokensForMod('')
      expect(result).toEqual({ read: '', write: '' })
    })

    it('returns empty tokens for undefined-like modId', () => {
      const result = readStoredDbTokensForMod('unknown')
      expect(result).toEqual({ read: '', write: '' })
    })
  })

  describe('saveStoredDbTokensForMod', () => {
    it('does not throw (stub) and dispatches event', () => {
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      saveStoredDbTokensForMod('mod1', 'read-tok', 'write-tok')
      expect(dispatchSpy).toHaveBeenCalled()
      const event = dispatchSpy.mock.calls[0][0] as CustomEvent
      expect(event.type).toBe(FHD_STORED_DB_TOKENS_CHANGED_EVENT)
      expect(event.detail).toEqual({ modId: 'mod1' })
    })

    it('clears legacy token storage', () => {
      localStorage.setItem(LS_DB_READ_TOKEN, 'legacy')
      localStorage.setItem(LS_DB_WRITE_TOKEN, 'legacy')
      localStorage.setItem(LS_DB_TOKENS_BY_MOD, 'legacy')

      saveStoredDbTokensForMod('mod1', 'r', 'w')

      expect(localStorage.getItem(LS_DB_READ_TOKEN)).toBeNull()
      expect(localStorage.getItem(LS_DB_WRITE_TOKEN)).toBeNull()
      expect(localStorage.getItem(LS_DB_TOKENS_BY_MOD)).toBeNull()
    })

    it('does not throw with empty modId', () => {
      expect(() => saveStoredDbTokensForMod('', '', '')).not.toThrow()
    })
  })

  describe('readStoredDbTokens', () => {
    it('returns empty read and write tokens (stub)', () => {
      const result = readStoredDbTokens()
      expect(result).toEqual({ read: '', write: '' })
    })
  })

  describe('saveStoredDbTokens', () => {
    it('does not throw (stub)', () => {
      expect(() => saveStoredDbTokens('r', 'w')).not.toThrow()
    })

    it('clears legacy token storage', () => {
      localStorage.setItem(LS_DB_READ_TOKEN, 'legacy')
      localStorage.setItem(LS_DB_WRITE_TOKEN, 'legacy')

      saveStoredDbTokens('r', 'w')

      expect(localStorage.getItem(LS_DB_READ_TOKEN)).toBeNull()
      expect(localStorage.getItem(LS_DB_WRITE_TOKEN)).toBeNull()
    })
  })

  describe('saveStoredReadToken', () => {
    it('does not throw (stub)', () => {
      expect(() => saveStoredReadToken('r')).not.toThrow()
    })

    it('clears legacy token storage', () => {
      localStorage.setItem(LS_DB_READ_TOKEN, 'legacy')

      saveStoredReadToken('r')

      expect(localStorage.getItem(LS_DB_READ_TOKEN)).toBeNull()
    })
  })

  describe('saveStoredWriteToken', () => {
    it('does not throw (stub)', () => {
      expect(() => saveStoredWriteToken('w')).not.toThrow()
    })

    it('clears legacy token storage', () => {
      localStorage.setItem(LS_DB_WRITE_TOKEN, 'legacy')

      saveStoredWriteToken('w')

      expect(localStorage.getItem(LS_DB_WRITE_TOKEN)).toBeNull()
    })
  })

  describe('getProductsReadLockState', () => {
    it('returns "open" (stub)', async () => {
      const result = await getProductsReadLockState()
      expect(result).toBe('open')
    })

    it('returns "open" with apiBase', async () => {
      const result = await getProductsReadLockState('https://api.example.com')
      expect(result).toBe('open')
    })

    it('returns "open" with options', async () => {
      const result = await getProductsReadLockState('', { allowStoredTokenBypassGrace: true })
      expect(result).toBe('open')
    })
  })

  describe('probeProductsReadAccess', () => {
    it('returns true (stub)', async () => {
      const result = await probeProductsReadAccess()
      expect(result).toBe(true)
    })

    it('returns true with apiBase', async () => {
      const result = await probeProductsReadAccess('https://api.example.com')
      expect(result).toBe(true)
    })

    it('returns true with options', async () => {
      const result = await probeProductsReadAccess('', { allowStoredTokenBypassGrace: false })
      expect(result).toBe(true)
    })
  })

  describe('urlNeedsDbReadToken', () => {
    it('returns false (stub)', () => {
      expect(urlNeedsDbReadToken('/api/products')).toBe(false)
    })

    it('returns false for empty url', () => {
      expect(urlNeedsDbReadToken('')).toBe(false)
    })

    it('returns false for any url', () => {
      expect(urlNeedsDbReadToken('https://api.example.com/api/fhd/products')).toBe(false)
    })
  })

  describe('shouldAttachDbReadToken', () => {
    it('returns false (stub)', () => {
      expect(shouldAttachDbReadToken('/api/products', 'GET')).toBe(false)
    })

    it('returns false for empty url', () => {
      expect(shouldAttachDbReadToken('', 'GET')).toBe(false)
    })

    it('returns false for any method', () => {
      expect(shouldAttachDbReadToken('/api/products', 'POST')).toBe(false)
      expect(shouldAttachDbReadToken('/api/products', 'PUT')).toBe(false)
      expect(shouldAttachDbReadToken('/api/products', 'DELETE')).toBe(false)
    })
  })

  describe('armNextPlannerChatDbWriteToken', () => {
    it('does not throw (stub)', () => {
      expect(() => armNextPlannerChatDbWriteToken()).not.toThrow()
    })
  })

  describe('isPlannerChatDbWriteTokenArmed', () => {
    it('returns false (stub)', () => {
      expect(isPlannerChatDbWriteTokenArmed()).toBe(false)
    })

    it('returns false after arming (stub)', () => {
      armNextPlannerChatDbWriteToken()
      expect(isPlannerChatDbWriteTokenArmed()).toBe(false)
    })
  })

  describe('consumePlannerChatDbWriteTokenArm', () => {
    it('does not throw (stub)', () => {
      expect(() => consumePlannerChatDbWriteTokenArm()).not.toThrow()
    })

    it('does not throw after arming (stub)', () => {
      armNextPlannerChatDbWriteToken()
      expect(() => consumePlannerChatDbWriteTokenArm()).not.toThrow()
    })
  })

  describe('notifyDbReadTokenRequiredAfter403', () => {
    it('does not throw (stub)', () => {
      expect(() => notifyDbReadTokenRequiredAfter403(403, '/api/products', 'GET')).not.toThrow()
    })

    it('does not throw with empty values', () => {
      expect(() => notifyDbReadTokenRequiredAfter403(0, '', '')).not.toThrow()
    })
  })

  describe('notifyDbWriteTokenRequiredAfter403', () => {
    it('does not throw (stub)', () => {
      expect(() => notifyDbWriteTokenRequiredAfter403(403, '/api/products', 'POST')).not.toThrow()
    })

    it('does not throw with empty values', () => {
      expect(() => notifyDbWriteTokenRequiredAfter403(0, '', '')).not.toThrow()
    })
  })

  describe('urlNeedsDbWriteToken', () => {
    it('returns false (stub)', () => {
      expect(urlNeedsDbWriteToken('/api/products', 'POST')).toBe(false)
    })

    it('returns false for empty url', () => {
      expect(urlNeedsDbWriteToken('', 'GET')).toBe(false)
    })

    it('returns false for any method', () => {
      expect(urlNeedsDbWriteToken('/api/products', 'GET')).toBe(false)
      expect(urlNeedsDbWriteToken('/api/products', 'PUT')).toBe(false)
      expect(urlNeedsDbWriteToken('/api/products', 'DELETE')).toBe(false)
    })
  })

  describe('combinedRequestUrl', () => {
    it('returns url when it is absolute http URL', () => {
      expect(combinedRequestUrl({ url: 'http://example.com/api/test' })).toBe(
        'http://example.com/api/test',
      )
    })

    it('returns url when it is absolute https URL', () => {
      expect(combinedRequestUrl({ url: 'https://example.com/api/test' })).toBe(
        'https://example.com/api/test',
      )
    })

    it('returns url when it is absolute HTTP URL (uppercase)', () => {
      expect(combinedRequestUrl({ url: 'HTTP://example.com/api/test' })).toBe(
        'HTTP://example.com/api/test',
      )
    })

    it('returns url when it is absolute HTTPS URL (uppercase)', () => {
      expect(combinedRequestUrl({ url: 'HTTPS://example.com/api/test' })).toBe(
        'HTTPS://example.com/api/test',
      )
    })

    it('combines baseURL and url with leading slash in url', () => {
      expect(combinedRequestUrl({ baseURL: 'https://api.example.com', url: '/api/test' })).toBe(
        'https://api.example.com/api/test',
      )
    })

    it('combines baseURL and url without leading slash in url', () => {
      expect(combinedRequestUrl({ baseURL: 'https://api.example.com', url: 'api/test' })).toBe(
        'https://api.example.com/api/test',
      )
    })

    it('strips trailing slash from baseURL', () => {
      expect(combinedRequestUrl({ baseURL: 'https://api.example.com/', url: '/api/test' })).toBe(
        'https://api.example.com/api/test',
      )
    })

    it('returns just path when baseURL is empty', () => {
      expect(combinedRequestUrl({ baseURL: '', url: '/api/test' })).toBe('/api/test')
    })

    it('returns just path when baseURL is undefined', () => {
      expect(combinedRequestUrl({ url: '/api/test' })).toBe('/api/test')
    })

    it('returns path with leading slash when url has no slash and baseURL is empty', () => {
      expect(combinedRequestUrl({ url: 'api/test' })).toBe('/api/test')
    })

    it('returns "/" when both baseURL and url are empty', () => {
      // u = '', path = '/' + '' = '/', b = '' so return path
      expect(combinedRequestUrl({ baseURL: '', url: '' })).toBe('/')
    })

    it('returns "/" when both baseURL and url are undefined', () => {
      // u = '' (default), path = '/' + '' = '/', b = '' so return path
      expect(combinedRequestUrl({})).toBe('/')
    })

    it('returns url when url is empty but baseURL is set (empty path with slash)', () => {
      expect(combinedRequestUrl({ baseURL: 'https://api.example.com', url: '' })).toBe(
        'https://api.example.com/',
      )
    })

    it('handles relative URL with no slash and no baseURL', () => {
      expect(combinedRequestUrl({ url: 'test' })).toBe('/test')
    })

    it('handles complex baseURL with path', () => {
      expect(
        combinedRequestUrl({ baseURL: 'https://api.example.com/v1', url: '/users' }),
      ).toBe('https://api.example.com/v1/users')
    })

    it('handles complex baseURL with path and trailing slash', () => {
      expect(
        combinedRequestUrl({ baseURL: 'https://api.example.com/v1/', url: '/users' }),
      ).toBe('https://api.example.com/v1/users')
    })
  })

  describe('dbReadHeaders', () => {
    it('returns empty object (stub)', () => {
      expect(dbReadHeaders()).toEqual({})
    })

    it('returns empty object with options', () => {
      expect(dbReadHeaders({ ignoreGrace: true })).toEqual({})
    })

    it('returns empty object with ignoreGrace false', () => {
      expect(dbReadHeaders({ ignoreGrace: false })).toEqual({})
    })
  })

  describe('dbWriteHeaders', () => {
    it('returns empty object (stub)', () => {
      expect(dbWriteHeaders()).toEqual({})
    })
  })
})

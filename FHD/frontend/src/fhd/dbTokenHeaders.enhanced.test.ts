import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  readStoredDbTokensForMod,
  saveStoredDbTokensForMod,
  readStoredDbTokens,
  saveStoredDbTokens,
  saveStoredReadToken,
  saveStoredWriteToken,
  urlNeedsDbReadToken,
  shouldAttachDbReadToken,
  urlNeedsDbWriteToken,
  combinedRequestUrl,
  isProductsReadGateGraceActive,
  touchProductsReadGateGrace,
  dbReadHeaders,
  dbWriteHeaders,
  armNextPlannerChatDbWriteToken,
  isPlannerChatDbWriteTokenArmed,
  consumePlannerChatDbWriteTokenArm,
  notifyDbReadTokenRequiredAfter403,
  notifyDbWriteTokenRequiredAfter403,
  LS_DB_READ_TOKEN,
  LS_DB_WRITE_TOKEN,
  LS_DB_TOKENS_BY_MOD,
  FHD_STORED_DB_TOKENS_CHANGED_EVENT,
  XCAGI_PROMPT_DB_READ_TOKEN_EVENT,
  XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT,
} from './dbTokenHeaders'

vi.mock('@/utils/xcagiStorageKeys', () => ({
  readActiveExtensionModIdFromStorage: () => localStorage.getItem('xcagi_active_mod_id') || '',
}))

describe('dbTokenHeaders – constants', () => {
  it('exports correct storage keys', () => {
    expect(LS_DB_READ_TOKEN).toBe('xcagi_db_read_token')
    expect(LS_DB_WRITE_TOKEN).toBe('xcagi_db_write_token')
    expect(LS_DB_TOKENS_BY_MOD).toBe('xcagi_db_tokens_by_mod')
  })

  it('exports event names', () => {
    expect(FHD_STORED_DB_TOKENS_CHANGED_EVENT).toContain('db-tokens')
    expect(XCAGI_PROMPT_DB_READ_TOKEN_EVENT).toContain('prompt-db-read-token')
    expect(XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT).toContain('prompt-db-write-token')
  })
})

describe('dbTokenHeaders – readStoredDbTokensForMod', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns empty strings when no tokens stored', () => {
    const tokens = readStoredDbTokensForMod('mod-a')
    expect(tokens).toEqual({ read: '', write: '' })
  })

  it('returns empty strings for empty modId', () => {
    expect(readStoredDbTokensForMod('')).toEqual({ read: '', write: '' })
  })

  it('reads tokens from localStorage', () => {
    localStorage.setItem(LS_DB_TOKENS_BY_MOD, JSON.stringify({
      'mod-a': { read: 'read-tok', write: 'write-tok' },
    }))
    const tokens = readStoredDbTokensForMod('mod-a')
    expect(tokens.read).toBe('read-tok')
    expect(tokens.write).toBe('write-tok')
  })

  it('handles malformed JSON gracefully', () => {
    localStorage.setItem(LS_DB_TOKENS_BY_MOD, 'not-json')
    const tokens = readStoredDbTokensForMod('mod-a')
    expect(tokens).toEqual({ read: '', write: '' })
  })

  it('handles non-object JSON gracefully', () => {
    localStorage.setItem(LS_DB_TOKENS_BY_MOD, '"string"')
    const tokens = readStoredDbTokensForMod('mod-a')
    expect(tokens).toEqual({ read: '', write: '' })
  })
})

describe('dbTokenHeaders – saveStoredDbTokensForMod', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('saves tokens for a mod', () => {
    saveStoredDbTokensForMod('mod-a', 'read-tok', 'write-tok')
    const stored = JSON.parse(localStorage.getItem(LS_DB_TOKENS_BY_MOD) || '{}')
    expect(stored['mod-a'].read).toBe('read-tok')
    expect(stored['mod-a'].write).toBe('write-tok')
  })

  it('removes mod entry when both tokens are empty', () => {
    saveStoredDbTokensForMod('mod-a', 'read', 'write')
    saveStoredDbTokensForMod('mod-a', '', '')
    const stored = JSON.parse(localStorage.getItem(LS_DB_TOKENS_BY_MOD) || '{}')
    expect(stored['mod-a']).toBeUndefined()
  })

  it('removes localStorage key when no mods remain', () => {
    saveStoredDbTokensForMod('mod-a', 'read', 'write')
    saveStoredDbTokensForMod('mod-a', '', '')
    expect(localStorage.getItem(LS_DB_TOKENS_BY_MOD)).toBeNull()
  })

  it('does nothing for empty modId', () => {
    saveStoredDbTokensForMod('', 'read', 'write')
    expect(localStorage.getItem(LS_DB_TOKENS_BY_MOD)).toBeNull()
  })

  it('dispatches change event', () => {
    const handler = vi.fn()
    window.addEventListener(FHD_STORED_DB_TOKENS_CHANGED_EVENT, handler)
    saveStoredDbTokensForMod('mod-a', 'read', '')
    window.removeEventListener(FHD_STORED_DB_TOKENS_CHANGED_EVENT, handler)
    expect(handler).toHaveBeenCalled()
  })
})

describe('dbTokenHeaders – readStoredDbTokens', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns global tokens when no active mod', () => {
    localStorage.setItem(LS_DB_READ_TOKEN, 'global-read')
    localStorage.setItem(LS_DB_WRITE_TOKEN, 'global-write')
    const tokens = readStoredDbTokens()
    expect(tokens.read).toBe('global-read')
    expect(tokens.write).toBe('global-write')
  })

  it('returns mod-specific tokens when active mod has them', () => {
    localStorage.setItem('xcagi_active_mod_id', 'mod-a')
    localStorage.setItem(LS_DB_READ_TOKEN, 'global-read')
    localStorage.setItem(LS_DB_TOKENS_BY_MOD, JSON.stringify({
      'mod-a': { read: 'mod-read', write: 'mod-write' },
    }))
    const tokens = readStoredDbTokens()
    expect(tokens.read).toBe('mod-read')
    expect(tokens.write).toBe('mod-write')
  })

  it('falls back to global when mod has no tokens', () => {
    localStorage.setItem('xcagi_active_mod_id', 'mod-a')
    localStorage.setItem(LS_DB_READ_TOKEN, 'global-read')
    const tokens = readStoredDbTokens()
    expect(tokens.read).toBe('global-read')
  })
})

describe('dbTokenHeaders – saveStoredDbTokens', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('saves global tokens', () => {
    saveStoredDbTokens('my-read', 'my-write')
    expect(localStorage.getItem(LS_DB_READ_TOKEN)).toBe('my-read')
    expect(localStorage.getItem(LS_DB_WRITE_TOKEN)).toBe('my-write')
  })

  it('removes tokens when empty', () => {
    localStorage.setItem(LS_DB_READ_TOKEN, 'old')
    saveStoredDbTokens('', '')
    expect(localStorage.getItem(LS_DB_READ_TOKEN)).toBeNull()
    expect(localStorage.getItem(LS_DB_WRITE_TOKEN)).toBeNull()
  })
})

describe('dbTokenHeaders – saveStoredReadToken / saveStoredWriteToken', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('saveStoredReadToken saves to mod when active', () => {
    localStorage.setItem('xcagi_active_mod_id', 'mod-a')
    saveStoredReadToken('new-read')
    const stored = JSON.parse(localStorage.getItem(LS_DB_TOKENS_BY_MOD) || '{}')
    expect(stored['mod-a'].read).toBe('new-read')
  })

  it('saveStoredReadToken saves globally when no active mod', () => {
    saveStoredReadToken('global-read')
    expect(localStorage.getItem(LS_DB_READ_TOKEN)).toBe('global-read')
  })

  it('saveStoredWriteToken saves to mod when active', () => {
    localStorage.setItem('xcagi_active_mod_id', 'mod-a')
    saveStoredWriteToken('new-write')
    const stored = JSON.parse(localStorage.getItem(LS_DB_TOKENS_BY_MOD) || '{}')
    expect(stored['mod-a'].write).toBe('new-write')
  })

  it('saveStoredWriteToken saves globally when no active mod', () => {
    saveStoredWriteToken('global-write')
    expect(localStorage.getItem(LS_DB_WRITE_TOKEN)).toBe('global-write')
  })
})

describe('dbTokenHeaders – urlNeedsDbReadToken', () => {
  it('returns true for products API', () => {
    expect(urlNeedsDbReadToken('/api/products/list')).toBe(true)
  })

  it('returns true for customers list API', () => {
    expect(urlNeedsDbReadToken('/api/customers/list')).toBe(true)
  })

  it('returns true for sales-contract template-preview', () => {
    expect(urlNeedsDbReadToken('/api/sales-contract/template-preview')).toBe(true)
  })

  it('returns false for unrelated API', () => {
    expect(urlNeedsDbReadToken('/api/auth/login')).toBe(false)
  })
})

describe('dbTokenHeaders – shouldAttachDbReadToken', () => {
  it('returns true for GET to protected path', () => {
    expect(shouldAttachDbReadToken('/api/products/list', 'GET')).toBe(true)
  })

  it('returns true for POST to resolve-from-text', () => {
    expect(shouldAttachDbReadToken('/api/sales-contract/resolve-from-text', 'POST')).toBe(true)
  })

  it('returns false for POST to products list', () => {
    expect(shouldAttachDbReadToken('/api/products/list', 'POST')).toBe(false)
  })

  it('returns false for non-protected path', () => {
    expect(shouldAttachDbReadToken('/api/auth/me', 'GET')).toBe(false)
  })
})

describe('dbTokenHeaders – urlNeedsDbWriteToken', () => {
  it('returns true for products update', () => {
    expect(urlNeedsDbWriteToken('/api/products/update', 'POST')).toBe(true)
  })

  it('returns true for products add', () => {
    expect(urlNeedsDbWriteToken('/api/products/add', 'POST')).toBe(true)
  })

  it('returns true for tools execute', () => {
    expect(urlNeedsDbWriteToken('/api/tools/execute', 'POST')).toBe(true)
  })

  it('returns true for customer import', () => {
    expect(urlNeedsDbWriteToken('/api/customers/import', 'POST')).toBe(true)
  })

  it('returns true for customer batch-delete', () => {
    expect(urlNeedsDbWriteToken('/api/customers/batch-delete', 'POST')).toBe(true)
  })

  it('returns true for customer PUT', () => {
    expect(urlNeedsDbWriteToken('/api/customers/123', 'PUT')).toBe(true)
  })

  it('returns true for customer DELETE', () => {
    expect(urlNeedsDbWriteToken('/api/customers/123', 'DELETE')).toBe(true)
  })

  it('returns false for GET requests', () => {
    expect(urlNeedsDbWriteToken('/api/products/update', 'GET')).toBe(false)
  })

  it('returns false for non-protected paths', () => {
    expect(urlNeedsDbWriteToken('/api/auth/login', 'POST')).toBe(false)
  })
})

describe('dbTokenHeaders – combinedRequestUrl', () => {
  it('combines baseURL and path', () => {
    expect(combinedRequestUrl({ baseURL: 'http://api', url: '/test' })).toBe('http://api/test')
  })

  it('returns full URL when url is absolute', () => {
    expect(combinedRequestUrl({ baseURL: 'http://api', url: 'http://other/test' })).toBe('http://other/test')
  })

  it('handles missing baseURL', () => {
    expect(combinedRequestUrl({ url: '/test' })).toBe('/test')
  })

  it('handles missing url', () => {
    expect(combinedRequestUrl({ baseURL: 'http://api' })).toBe('http://api/')
  })
})

describe('dbTokenHeaders – grace period', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('grace is inactive by default', () => {
    expect(isProductsReadGateGraceActive()).toBe(false)
  })

  it('grace activates after touch', () => {
    touchProductsReadGateGrace()
    expect(isProductsReadGateGraceActive()).toBe(true)
  })
})

describe('dbTokenHeaders – dbReadHeaders / dbWriteHeaders', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('dbReadHeaders returns empty when no token stored', () => {
    expect(dbReadHeaders()).toEqual({})
  })

  it('dbReadHeaders returns header when token stored', () => {
    localStorage.setItem(LS_DB_READ_TOKEN, 'my-token')
    expect(dbReadHeaders()).toEqual({ 'X-FHD-Db-Read-Token': 'my-token' })
  })

  it('dbWriteHeaders returns empty when no token stored', () => {
    expect(dbWriteHeaders()).toEqual({})
  })

  it('dbWriteHeaders returns header when token stored', () => {
    localStorage.setItem(LS_DB_WRITE_TOKEN, 'my-write')
    expect(dbWriteHeaders()).toEqual({ 'X-FHD-Db-Write-Token': 'my-write' })
  })
})

describe('dbTokenHeaders – planner chat db write token', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('is not armed by default', () => {
    expect(isPlannerChatDbWriteTokenArmed()).toBe(false)
  })

  it('is armed after armNextPlannerChatDbWriteToken', () => {
    armNextPlannerChatDbWriteToken()
    expect(isPlannerChatDbWriteTokenArmed()).toBe(true)
  })

  it('is not armed after consume', () => {
    armNextPlannerChatDbWriteToken()
    consumePlannerChatDbWriteTokenArm()
    expect(isPlannerChatDbWriteTokenArmed()).toBe(false)
  })
})

describe('dbTokenHeaders – notifyDbReadTokenRequiredAfter403', () => {
  it('dispatches event for 403 on protected path', () => {
    const handler = vi.fn()
    window.addEventListener(XCAGI_PROMPT_DB_READ_TOKEN_EVENT, handler)
    notifyDbReadTokenRequiredAfter403(403, '/api/products/list', 'GET')
    window.removeEventListener(XCAGI_PROMPT_DB_READ_TOKEN_EVENT, handler)
    expect(handler).toHaveBeenCalled()
  })

  it('does not dispatch for non-403', () => {
    const handler = vi.fn()
    window.addEventListener(XCAGI_PROMPT_DB_READ_TOKEN_EVENT, handler)
    notifyDbReadTokenRequiredAfter403(200, '/api/products/list', 'GET')
    window.removeEventListener(XCAGI_PROMPT_DB_READ_TOKEN_EVENT, handler)
    expect(handler).not.toHaveBeenCalled()
  })

  it('does not dispatch for non-protected path', () => {
    const handler = vi.fn()
    window.addEventListener(XCAGI_PROMPT_DB_READ_TOKEN_EVENT, handler)
    notifyDbReadTokenRequiredAfter403(403, '/api/auth/me', 'GET')
    window.removeEventListener(XCAGI_PROMPT_DB_READ_TOKEN_EVENT, handler)
    expect(handler).not.toHaveBeenCalled()
  })
})

describe('dbTokenHeaders – notifyDbWriteTokenRequiredAfter403', () => {
  it('dispatches event for 403 on write-protected path', () => {
    const handler = vi.fn()
    window.addEventListener(XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT, handler)
    notifyDbWriteTokenRequiredAfter403(403, '/api/products/update', 'POST')
    window.removeEventListener(XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT, handler)
    expect(handler).toHaveBeenCalled()
  })

  it('does not dispatch for non-write-protected path', () => {
    const handler = vi.fn()
    window.addEventListener(XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT, handler)
    notifyDbWriteTokenRequiredAfter403(403, '/api/products/list', 'GET')
    window.removeEventListener(XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT, handler)
    expect(handler).not.toHaveBeenCalled()
  })
})

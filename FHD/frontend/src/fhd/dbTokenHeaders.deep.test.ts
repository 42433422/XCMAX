import { describe, expect, it } from 'vitest'

import {
  dbReadHeaders,
  dbWriteHeaders,
  notifyDbReadTokenRequiredAfter403,
  notifyDbWriteTokenRequiredAfter403,
  saveStoredDbTokens,
  saveStoredReadToken,
  saveStoredWriteToken,
  urlNeedsDbReadToken,
  urlNeedsDbWriteToken,
} from '@/fhd/dbTokenHeaders'

describe('dbTokenHeaders deep compatibility', () => {
  it('never stores, emits, or attaches database password tokens', () => {
    localStorage.setItem('xcagi_db_read_token', 'old-read')
    localStorage.setItem('xcagi_db_write_token', 'old-write')
    saveStoredDbTokens('read', 'write')
    saveStoredReadToken('read')
    saveStoredWriteToken('write')

    expect(localStorage.getItem('xcagi_db_read_token')).toBeNull()
    expect(localStorage.getItem('xcagi_db_write_token')).toBeNull()
    expect(dbReadHeaders()).toEqual({})
    expect(dbWriteHeaders()).toEqual({})
    expect(urlNeedsDbReadToken('/api/products/list')).toBe(false)
    expect(urlNeedsDbWriteToken('/api/products/update', 'POST')).toBe(false)
    expect(() => notifyDbReadTokenRequiredAfter403(403, '/api/products/list', 'GET')).not.toThrow()
    expect(() => notifyDbWriteTokenRequiredAfter403(403, '/api/products/update', 'POST')).not.toThrow()
  })
})

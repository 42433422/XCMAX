import { describe, expect, it } from 'vitest'

import {
  dbReadHeaders,
  dbWriteHeaders,
  getProductsReadLockState,
  isProductsReadGateGraceActive,
  probeProductsReadAccess,
  readStoredDbTokens,
  shouldAttachDbReadToken,
  urlNeedsDbReadToken,
  urlNeedsDbWriteToken,
} from '@/fhd/dbTokenHeaders'

describe('dbTokenHeaders', () => {
  it('keeps database password gates disabled', async () => {
    expect(readStoredDbTokens()).toEqual({ read: '', write: '' })
    expect(dbReadHeaders()).toEqual({})
    expect(dbWriteHeaders()).toEqual({})
    expect(isProductsReadGateGraceActive()).toBe(false)
    expect(urlNeedsDbReadToken('/api/products/list')).toBe(false)
    expect(shouldAttachDbReadToken('/api/products/list', 'GET')).toBe(false)
    expect(urlNeedsDbWriteToken('/api/products/update', 'POST')).toBe(false)
    await expect(getProductsReadLockState()).resolves.toBe('open')
    await expect(probeProductsReadAccess()).resolves.toBe(true)
  })
})

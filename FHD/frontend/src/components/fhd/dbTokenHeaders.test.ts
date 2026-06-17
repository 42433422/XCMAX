import { describe, expect, it } from 'vitest'

import { dbReadHeaders, dbWriteHeaders, urlNeedsDbWriteToken } from './dbTokenHeaders'

describe('components/fhd dbTokenHeaders re-export', () => {
  it('re-exports inert database password helpers', () => {
    expect(dbReadHeaders()).toEqual({})
    expect(dbWriteHeaders()).toEqual({})
    expect(urlNeedsDbWriteToken('/api/products/update', 'POST')).toBe(false)
  })
})

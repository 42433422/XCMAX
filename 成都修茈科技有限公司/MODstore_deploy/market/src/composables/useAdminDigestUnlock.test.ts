import { describe, expect, it } from 'vitest'
import { normalizeAdminDigestCode } from './useAdminDigestUnlock'

describe('normalizeAdminDigestCode', () => {
  it('strips non-hex and uppercases', () => {
    expect(normalizeAdminDigestCode('a5 06 e7')).toBe('A506E7')
  })

  it('truncates to 6', () => {
    expect(normalizeAdminDigestCode('A506E7FF')).toBe('A506E7')
  })
})

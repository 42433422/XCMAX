import { describe, it, expect } from 'vitest'
import { toNumber } from './textParser'

describe('textParser extended branches', () => {
  it('toNumber parses numeric strings', () => {
    expect(toNumber('12.5')).toBe(12.5)
    expect(toNumber('abc')).toBeNull()
    expect(toNumber('')).toBe(0)
  })
})

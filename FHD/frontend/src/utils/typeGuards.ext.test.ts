import { describe, it, expect } from 'vitest'
import { asBoolean, asNumber, asString, asDisposable } from './typeGuards'

describe('typeGuards branch sweep', () => {
  it('asBoolean handles false string and numeric one', () => {
    expect(asBoolean('false')).toBe(false)
    expect(asBoolean(1)).toBe(true)
    expect(asBoolean(false)).toBe(false)
    expect(asBoolean(undefined, false)).toBe(false)
  })

  it('asNumber handles NaN and Infinity', () => {
    expect(asNumber(NaN, 7)).toBe(7)
    expect(asNumber(Infinity, 3)).toBe(3)
    expect(asNumber(0)).toBe(0)
  })

  it('asString handles undefined with empty fallback', () => {
    expect(asString(undefined)).toBe('')
    expect(asString(false)).toBe('false')
  })

  it('asDisposable accepts destroy and cleanup', () => {
    expect(asDisposable({ destroy: () => {} })).toBeTruthy()
    expect(asDisposable({ cleanup: () => {} })).toBeTruthy()
    expect(asDisposable(null)).toBeNull()
  })
})

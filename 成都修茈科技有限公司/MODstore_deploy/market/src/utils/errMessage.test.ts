import { describe, expect, it } from 'vitest'
import { errMessage } from './errMessage'

describe('errMessage', () => {
  it('extracts message from Error instance', () => {
    expect(errMessage(new Error('test error'))).toBe('test error')
  })

  it('extracts message from object with message property', () => {
    expect(errMessage({ message: 'object error' })).toBe('object error')
  })

  it('extracts message from object with non-string message', () => {
    expect(errMessage({ message: 42 })).toBe('[object Object]')
  })

  it('converts string to string', () => {
    expect(errMessage('plain string')).toBe('plain string')
  })

  it('converts number to string', () => {
    expect(errMessage(404)).toBe('404')
  })

  it('converts null to string', () => {
    expect(errMessage(null)).toBe('null')
  })

  it('converts undefined to string', () => {
    expect(errMessage(undefined)).toBe('undefined')
  })

  it('converts object without message to string', () => {
    const result = errMessage({ code: 500 })
    expect(typeof result).toBe('string')
    expect(result.length).toBeGreaterThan(0)
  })
})

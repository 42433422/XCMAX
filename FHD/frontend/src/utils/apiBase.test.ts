import { describe, it, expect } from 'vitest'
import { isApiFetchTimeoutError } from './apiBase'

describe('apiBase', () => {
  it('isApiFetchTimeoutError detects apiFetch timeout AbortError', () => {
    const err = new DOMException('apiFetch timeout after 1000ms', 'AbortError')
    expect(isApiFetchTimeoutError(err)).toBe(true)
  })

  it('isApiFetchTimeoutError ignores generic AbortError', () => {
    const err = new DOMException('user aborted', 'AbortError')
    expect(isApiFetchTimeoutError(err)).toBe(false)
  })

  it('isApiFetchTimeoutError handles Error shape', () => {
    const err = new Error('apiFetch timeout')
    err.name = 'AbortError'
    expect(isApiFetchTimeoutError(err)).toBe(true)
  })
})

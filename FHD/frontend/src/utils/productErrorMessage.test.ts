import { describe, expect, it } from 'vitest'
import { productErrorMessage } from './productErrorMessage'

describe('productErrorMessage', () => {
  it('maps 401 to friendly login message', () => {
    expect(productErrorMessage('HTTP 401 Unauthorized', 'fallback')).toContain('登录')
  })

  it('maps timeout to relay hint', () => {
    expect(productErrorMessage('connect ETIMEDOUT', 'fallback')).toContain('中继')
  })

  it('uses fallback for long technical errors', () => {
    expect(productErrorMessage('x'.repeat(100), '短提示')).toBe('短提示')
  })
})

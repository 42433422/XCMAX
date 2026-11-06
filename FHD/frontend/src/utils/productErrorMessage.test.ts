import { describe, expect, it } from 'vitest'
import { productErrorMessage } from './productErrorMessage'

describe('productErrorMessage', () => {
  it('maps 401 to friendly login message', () => {
    expect(productErrorMessage('HTTP 401 Unauthorized', 'fallback')).toContain('登录')
  })

  it('maps ETIMEDOUT to a timeout, not the relay hint', () => {
    const message = productErrorMessage('connect ETIMEDOUT', 'fallback')
    expect(message).toContain('请求超时')
    expect(message).not.toContain('中继')
  })

  it('uses fallback for long technical errors', () => {
    expect(productErrorMessage('x'.repeat(100), '短提示')).toBe('短提示')
  })
})

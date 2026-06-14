import { describe, expect, it } from 'vitest'
import { easingFunctions } from './useAnimations'

describe('useAnimations easingFunctions', () => {
  it('linear at boundaries', () => {
    expect(easingFunctions.linear(0)).toBe(0)
    expect(easingFunctions.linear(1)).toBe(1)
  })

  it('easeInQuad increases', () => {
    expect(easingFunctions.easeInQuad(0.5)).toBeGreaterThan(0)
    expect(easingFunctions.easeInQuad(0.5)).toBeLessThan(1)
  })

  it('easeOutBounce ends at 1', () => {
    expect(easingFunctions.easeOutBounce(1)).toBeCloseTo(1, 2)
  })

  it('elastic easings handle 0 and 1', () => {
    expect(easingFunctions.easeInElastic(0)).toBe(0)
    expect(easingFunctions.easeOutElastic(1)).toBe(1)
  })
})

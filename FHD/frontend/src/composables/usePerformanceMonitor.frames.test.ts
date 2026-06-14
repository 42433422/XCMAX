import { describe, it, expect, vi } from 'vitest'
import { useFrameRateLimiter, useAnimationFrame } from './usePerformanceMonitor'

describe('useFrameRateLimiter', () => {
  it('exposes frame interval for target FPS', () => {
    const limiter = useFrameRateLimiter(60)
    expect(limiter.frameInterval).toBe(1000 / 60)
    limiter.cancelThrottle()
  })
})

describe('useAnimationFrame', () => {
  it('starts and stops animation loop', () => {
    const anim = useAnimationFrame()
    const cb = vi.fn()
    anim.start(cb)
    expect(anim.isRunning.value).toBe(true)
    anim.stop()
    expect(anim.isRunning.value).toBe(false)
    anim.updateCallback(vi.fn())
  })
})

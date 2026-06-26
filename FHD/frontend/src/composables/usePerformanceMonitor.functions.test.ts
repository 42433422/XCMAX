import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useFrameRateLimiter, useAnimationFrame } from './usePerformanceMonitor'

describe('usePerformanceMonitor utilities', () => {
  describe('useFrameRateLimiter', () => {
    it('returns object with shouldRender, throttle, cancelThrottle, frameInterval', () => {
      const limiter = useFrameRateLimiter(60)
      expect(typeof limiter.shouldRender).toBe('function')
      expect(typeof limiter.throttle).toBe('function')
      expect(typeof limiter.cancelThrottle).toBe('function')
      expect(typeof limiter.frameInterval).toBe('number')
    })

    it('calculates frameInterval correctly for 60 FPS', () => {
      const limiter = useFrameRateLimiter(60)
      expect(limiter.frameInterval).toBeCloseTo(1000 / 60, 1)
    })

    it('calculates frameInterval correctly for 30 FPS', () => {
      const limiter = useFrameRateLimiter(30)
      expect(limiter.frameInterval).toBeCloseTo(1000 / 30, 1)
    })

    it('shouldRender returns true on first call', () => {
      const limiter = useFrameRateLimiter(60)
      expect(limiter.shouldRender(1000)).toBe(true)
    })

    it('shouldRender returns false when within frame interval', () => {
      const limiter = useFrameRateLimiter(10)
      limiter.shouldRender(1000)
      expect(limiter.shouldRender(1001)).toBe(false)
    })

    it('shouldRender returns true when enough time has passed', () => {
      const limiter = useFrameRateLimiter(60)
      limiter.shouldRender(1000)
      expect(limiter.shouldRender(1000 + limiter.frameInterval + 1)).toBe(true)
    })

    it('throttle wraps callback and only calls when shouldRender is true', () => {
      const limiter = useFrameRateLimiter(10)
      const cb = vi.fn()
      const throttled = limiter.throttle(cb)
      throttled(1000)
      expect(cb).toHaveBeenCalledOnce()
      throttled(1001)
      expect(cb).toHaveBeenCalledOnce()
    })

    it('cancelThrottle does not throw', () => {
      const limiter = useFrameRateLimiter(60)
      expect(() => limiter.cancelThrottle()).not.toThrow()
    })
  })

  describe('useAnimationFrame', () => {
    it('returns object with isRunning, start, stop, updateCallback', () => {
      const anim = useAnimationFrame()
      expect(anim.isRunning.value).toBe(false)
      expect(typeof anim.start).toBe('function')
      expect(typeof anim.stop).toBe('function')
      expect(typeof anim.updateCallback).toBe('function')
    })

    it('start sets isRunning to true', () => {
      const anim = useAnimationFrame()
      anim.start(() => {})
      expect(anim.isRunning.value).toBe(true)
      anim.stop()
    })

    it('stop sets isRunning to false', () => {
      const anim = useAnimationFrame()
      anim.start(() => {})
      anim.stop()
      expect(anim.isRunning.value).toBe(false)
    })

    it('start does nothing if already running', () => {
      const anim = useAnimationFrame()
      anim.start(() => {})
      const cb2 = vi.fn()
      anim.start(cb2)
      // Should not overwrite the first callback
      expect(cb2).not.toHaveBeenCalled()
      anim.stop()
    })

    it('updateCallback changes the callback', () => {
      const anim = useAnimationFrame()
      const cb1 = vi.fn()
      const cb2 = vi.fn()
      anim.start(cb1)
      anim.updateCallback(cb2)
      // The new callback should be used on next frame
      anim.stop()
    })

    it('stop when not running does not throw', () => {
      const anim = useAnimationFrame()
      expect(() => anim.stop()).not.toThrow()
    })
  })
})

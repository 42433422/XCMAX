import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  makeTimerGroup,
  getVirtualCursor,
  cursorClick,
  safeClick,
  fireKey,
  highlightElement,
  sleep,
  TUTORIAL_DEMO_SPEED,
} from './demoHelpers'

describe('demoHelpers', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('TUTORIAL_DEMO_SPEED', () => {
    it('exports a number constant', () => {
      expect(typeof TUTORIAL_DEMO_SPEED).toBe('number')
      expect(TUTORIAL_DEMO_SPEED).toBeGreaterThan(0)
    })
  })

  describe('makeTimerGroup', () => {
    it('returns an object with set and clear methods', () => {
      const group = makeTimerGroup()
      expect(typeof group.set).toBe('function')
      expect(typeof group.clear).toBe('function')
    })

    it('set schedules a callback via setTimeout', () => {
      const group = makeTimerGroup()
      const cb = vi.fn()
      group.set(cb, 100)
      expect(cb).not.toHaveBeenCalled()
      vi.advanceTimersByTime(100)
      expect(cb).toHaveBeenCalledTimes(1)
    })

    it('clear cancels all scheduled timers', () => {
      const group = makeTimerGroup()
      const cb = vi.fn()
      group.set(cb, 100)
      group.set(cb, 200)
      group.clear()
      vi.advanceTimersByTime(300)
      expect(cb).not.toHaveBeenCalled()
    })

    it('clear can be called multiple times safely', () => {
      const group = makeTimerGroup()
      expect(() => {
        group.clear()
        group.clear()
      }).not.toThrow()
    })

    it('set can schedule multiple callbacks', () => {
      const group = makeTimerGroup()
      const cb1 = vi.fn()
      const cb2 = vi.fn()
      group.set(cb1, 100)
      group.set(cb2, 200)
      vi.advanceTimersByTime(150)
      expect(cb1).toHaveBeenCalledTimes(1)
      expect(cb2).not.toHaveBeenCalled()
      vi.advanceTimersByTime(100)
      expect(cb2).toHaveBeenCalledTimes(1)
    })
  })

  describe('getVirtualCursor', () => {
    it('returns undefined when window.virtualCursor is not set', () => {
      delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
      expect(getVirtualCursor()).toBeUndefined()
    })

    it('returns the virtualCursor when set', () => {
      const fake = { click: vi.fn() }
      ;(window as unknown as { virtualCursor?: unknown }).virtualCursor = fake
      try {
        expect(getVirtualCursor()).toBe(fake)
      } finally {
        delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
      }
    })
  })

  describe('cursorClick', () => {
    it('calls virtualCursor.click when available', () => {
      const clickSpy = vi.fn()
      ;(window as unknown as { virtualCursor?: unknown }).virtualCursor = { click: clickSpy }
      const el = document.createElement('button')
      try {
        cursorClick(el, 'label', 100)
        expect(clickSpy).toHaveBeenCalledWith(el, { duration: 100, label: 'label' })
      } finally {
        delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
      }
    })

    it('clicks the element after duration', () => {
      delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
      const el = document.createElement('button')
      const clickSpy = vi.fn()
      el.click = clickSpy
      el.scrollIntoView = vi.fn()
      cursorClick(el, undefined, 100)
      expect(clickSpy).not.toHaveBeenCalled()
      vi.advanceTimersByTime(100)
      expect(clickSpy).toHaveBeenCalledTimes(1)
    })

    it('uses default duration when not specified', () => {
      delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
      const el = document.createElement('button')
      const clickSpy = vi.fn()
      el.click = clickSpy
      el.scrollIntoView = vi.fn()
      cursorClick(el)
      vi.advanceTimersByTime(700 * TUTORIAL_DEMO_SPEED - 1)
      expect(clickSpy).not.toHaveBeenCalled()
      vi.advanceTimersByTime(1)
      expect(clickSpy).toHaveBeenCalledTimes(1)
    })

    it('handles scrollIntoView errors gracefully', () => {
      delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
      const el = document.createElement('button')
      el.click = vi.fn()
      el.scrollIntoView = () => {
        throw new Error('scroll failed')
      }
      cursorClick(el, undefined, 100)
      vi.advanceTimersByTime(100)
      // Should not throw, click should still happen
    })
  })

  describe('safeClick', () => {
    it('returns false when element not found', () => {
      expect(safeClick('.nonexistent')).toBe(false)
    })

    it('returns true and clicks when element found', () => {
      const el = document.createElement('button')
      el.className = 'test-btn'
      document.body.appendChild(el)
      const clickSpy = vi.fn()
      el.click = clickSpy
      el.scrollIntoView = vi.fn()
      try {
        delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
        const result = safeClick('.test-btn', 'label', 100)
        expect(result).toBe(true)
        vi.advanceTimersByTime(100)
        expect(clickSpy).toHaveBeenCalledTimes(1)
      } finally {
        document.body.removeChild(el)
      }
    })

    it('handles scrollIntoView errors gracefully', () => {
      const el = document.createElement('button')
      el.className = 'test-btn2'
      document.body.appendChild(el)
      el.click = vi.fn()
      el.scrollIntoView = () => {
        throw new Error('scroll failed')
      }
      try {
        delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
        expect(() => safeClick('.test-btn2', undefined, 100)).not.toThrow()
      } finally {
        document.body.removeChild(el)
      }
    })
  })

  describe('fireKey', () => {
    it('dispatches a keydown event with the given key and code', () => {
      const spy = vi.fn()
      document.addEventListener('keydown', spy)
      fireKey('Enter', 'Enter')
      document.removeEventListener('keydown', spy)
      expect(spy).toHaveBeenCalledTimes(1)
      const ev = spy.mock.calls[0][0] as KeyboardEvent
      expect(ev.key).toBe('Enter')
      expect(ev.code).toBe('Enter')
      expect(ev.bubbles).toBe(true)
    })

    it('sets metaKey when meta is true on Mac', () => {
      const origPlatform = navigator.platform
      Object.defineProperty(navigator, 'platform', { value: 'MacIntel', configurable: true })
      try {
        const spy = vi.fn()
        document.addEventListener('keydown', spy)
        fireKey('k', 'KeyK', true)
        document.removeEventListener('keydown', spy)
        const ev = spy.mock.calls[0][0] as KeyboardEvent
        expect(ev.metaKey).toBe(true)
        expect(ev.ctrlKey).toBe(false)
      } finally {
        Object.defineProperty(navigator, 'platform', { value: origPlatform, configurable: true })
      }
    })

    it('sets ctrlKey when meta is true on non-Mac', () => {
      const origPlatform = navigator.platform
      Object.defineProperty(navigator, 'platform', { value: 'Win32', configurable: true })
      try {
        const spy = vi.fn()
        document.addEventListener('keydown', spy)
        fireKey('k', 'KeyK', true)
        document.removeEventListener('keydown', spy)
        const ev = spy.mock.calls[0][0] as KeyboardEvent
        expect(ev.metaKey).toBe(false)
        expect(ev.ctrlKey).toBe(true)
      } finally {
        Object.defineProperty(navigator, 'platform', { value: origPlatform, configurable: true })
      }
    })

    it('does not set meta or ctrl when meta is false', () => {
      const spy = vi.fn()
      document.addEventListener('keydown', spy)
      fireKey('a', 'KeyA', false)
      document.removeEventListener('keydown', spy)
      const ev = spy.mock.calls[0][0] as KeyboardEvent
      expect(ev.metaKey).toBe(false)
      expect(ev.ctrlKey).toBe(false)
    })
  })

  describe('highlightElement', () => {
    it('sets outline styles on element', () => {
      const el = document.createElement('div')
      highlightElement(el, 100)
      expect(el.style.outline).toBe('2px solid #3b82f6')
      expect(el.style.outlineOffset).toBe('4px')
      expect(el.style.transition).toContain('outline')
    })

    it('clears outline after duration', () => {
      const el = document.createElement('div')
      highlightElement(el, 100)
      vi.advanceTimersByTime(100)
      expect(el.style.outline).toBe('')
      expect(el.style.outlineOffset).toBe('')
    })

    it('uses default duration when not specified', () => {
      const el = document.createElement('div')
      highlightElement(el)
      expect(el.style.outline).toBe('2px solid #3b82f6')
      vi.advanceTimersByTime(1500 * TUTORIAL_DEMO_SPEED - 1)
      expect(el.style.outline).toBe('2px solid #3b82f6')
      vi.advanceTimersByTime(1)
      expect(el.style.outline).toBe('')
    })
  })

  describe('sleep', () => {
    it('resolves after the specified time', async () => {
      let resolved = false
      sleep(100).then(() => {
        resolved = true
      })
      vi.advanceTimersByTime(99)
      await Promise.resolve()
      expect(resolved).toBe(false)
      vi.advanceTimersByTime(1)
      await Promise.resolve()
      expect(resolved).toBe(true)
    })

    it('resolves with undefined', async () => {
      const p = sleep(50)
      vi.advanceTimersByTime(50)
      await expect(p).resolves.toBeUndefined()
    })

    it('handles zero milliseconds', async () => {
      const p = sleep(0)
      vi.advanceTimersByTime(0)
      await expect(p).resolves.toBeUndefined()
    })
  })
})

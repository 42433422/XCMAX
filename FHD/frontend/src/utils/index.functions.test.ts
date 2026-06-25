import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  escapeHtml,
  generateSessionId,
  getFilenameFromDisposition,
  downloadBlob,
  formatDate,
  formatTime,
  debounce,
  throttle,
} from './index'

describe('utils/index pure functions', () => {
  describe('escapeHtml', () => {
    it('escapes HTML special characters', () => {
      expect(escapeHtml('<script>alert("xss")</script>')).toBe(
        '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;',
      )
    })

    it('escapes ampersand first to avoid double-encoding', () => {
      expect(escapeHtml('&lt;')).toBe('&amp;lt;')
    })

    it('escapes single quotes', () => {
      expect(escapeHtml("it's")).toBe('it&#39;s')
    })

    it('returns empty string for null/undefined', () => {
      expect(escapeHtml(null)).toBe('')
      expect(escapeHtml(undefined)).toBe('')
    })

    it('returns empty string for empty input', () => {
      expect(escapeHtml('')).toBe('')
    })

    it('converts non-string to string then escapes', () => {
      expect(escapeHtml(42)).toBe('42')
      expect(escapeHtml(0)).toBe('0')
    })

    it('handles plain text without special chars unchanged', () => {
      expect(escapeHtml('hello world')).toBe('hello world')
    })
  })

  describe('generateSessionId', () => {
    it('generates a string starting with session_', () => {
      const id = generateSessionId()
      expect(id).toMatch(/^session_\d+_[a-z0-9]+$/)
    })

    it('generates unique IDs on successive calls', () => {
      const ids = new Set<string>()
      for (let i = 0; i < 100; i++) {
        ids.add(generateSessionId())
      }
      expect(ids.size).toBe(100)
    })
  })

  describe('getFilenameFromDisposition', () => {
    it('returns fallback when disposition is null', () => {
      expect(getFilenameFromDisposition(null)).toBe('下载文件.xlsx')
    })

    it('returns custom fallback when disposition is null', () => {
      expect(getFilenameFromDisposition(null, 'custom.txt')).toBe('custom.txt')
    })

    it('returns fallback when disposition is empty string', () => {
      expect(getFilenameFromDisposition('')).toBe('下载文件.xlsx')
    })

    it('parses UTF-8 encoded filename', () => {
      const encoded = encodeURIComponent('中文文件.xlsx')
      expect(getFilenameFromDisposition(`attachment; filename*=UTF-8''${encoded}`)).toBe(
        '中文文件.xlsx',
      )
    })

    it('parses plain filename without quotes', () => {
      expect(getFilenameFromDisposition('attachment; filename=report.pdf')).toBe('report.pdf')
    })

    it('parses quoted filename', () => {
      expect(getFilenameFromDisposition('attachment; filename="my file.csv"')).toBe('my file.csv')
    })

    it('prefers UTF-8 filename over plain filename', () => {
      const encoded = encodeURIComponent('中文.xlsx')
      const disposition = `attachment; filename=fallback.xlsx; filename*=UTF-8''${encoded}`
      expect(getFilenameFromDisposition(disposition)).toBe('中文.xlsx')
    })

    it('returns fallback when no filename pattern matches', () => {
      expect(getFilenameFromDisposition('attachment')).toBe('下载文件.xlsx')
    })
  })

  describe('downloadBlob', () => {
    beforeEach(() => {
      vi.useFakeTimers()
      if (!URL.createObjectURL) (URL as any).createObjectURL = vi.fn(() => 'blob:url')
      if (!URL.revokeObjectURL) (URL as any).revokeObjectURL = vi.fn()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('creates a link and triggers click', () => {
      const createSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:url')
      const revokeSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})

      const blob = new Blob(['test'], { type: 'text/plain' })
      downloadBlob(blob, 'test.txt')

      expect(createSpy).toHaveBeenCalledWith(blob)
      vi.advanceTimersByTime(10)
      expect(revokeSpy).toHaveBeenCalledWith('blob:url')

      createSpy.mockRestore()
      revokeSpy.mockRestore()
    })
  })

  describe('formatDate', () => {
    it('formats a date string', () => {
      const result = formatDate('2024-01-15')
      expect(result).toMatch(/2024/)
      expect(result).toMatch(/01/)
      expect(result).toMatch(/15/)
    })

    it('formats a Date object', () => {
      const result = formatDate(new Date(2024, 5, 1))
      expect(result).toMatch(/2024/)
    })

    it('formats a timestamp number', () => {
      const result = formatDate(new Date(2024, 0, 1).getTime())
      expect(result).toMatch(/2024/)
    })

    it('handles invalid date without throwing', () => {
      expect(() => formatDate('invalid')).not.toThrow()
    })
  })

  describe('formatTime', () => {
    it('formats a date string to time', () => {
      const result = formatTime('2024-01-15T10:30:00')
      expect(result).toMatch(/10/)
      expect(result).toMatch(/30/)
    })

    it('formats a Date object', () => {
      const result = formatTime(new Date(2024, 5, 1, 14, 30))
      expect(result).toMatch(/14/)
      expect(result).toMatch(/30/)
    })

    it('handles invalid date without throwing', () => {
      expect(() => formatTime('invalid')).not.toThrow()
    })
  })

  describe('debounce', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('calls function after wait time', () => {
      const fn = vi.fn()
      const debounced = debounce(fn, 100)
      debounced()
      expect(fn).not.toHaveBeenCalled()
      vi.advanceTimersByTime(100)
      expect(fn).toHaveBeenCalledOnce()
    })

    it('does not call function before wait time', () => {
      const fn = vi.fn()
      const debounced = debounce(fn, 100)
      debounced()
      vi.advanceTimersByTime(50)
      expect(fn).not.toHaveBeenCalled()
    })

    it('resets timer on subsequent calls', () => {
      const fn = vi.fn()
      const debounced = debounce(fn, 100)
      debounced()
      vi.advanceTimersByTime(50)
      debounced()
      vi.advanceTimersByTime(50)
      expect(fn).not.toHaveBeenCalled()
      vi.advanceTimersByTime(50)
      expect(fn).toHaveBeenCalledOnce()
    })

    it('passes arguments to the function', () => {
      const fn = vi.fn()
      const debounced = debounce(fn, 100)
      debounced('a', 'b')
      vi.advanceTimersByTime(100)
      expect(fn).toHaveBeenCalledWith('a', 'b')
    })
  })

  describe('throttle', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('calls function immediately on first call', () => {
      const fn = vi.fn()
      const throttled = throttle(fn, 100)
      throttled()
      expect(fn).toHaveBeenCalledOnce()
    })

    it('does not call function again within limit', () => {
      const fn = vi.fn()
      const throttled = throttle(fn, 100)
      throttled()
      throttled()
      throttled()
      expect(fn).toHaveBeenCalledOnce()
    })

    it('calls function again after limit period', () => {
      const fn = vi.fn()
      const throttled = throttle(fn, 100)
      throttled()
      vi.advanceTimersByTime(100)
      throttled()
      expect(fn).toHaveBeenCalledTimes(2)
    })

    it('passes arguments and preserves this context', () => {
      const fn = vi.fn()
      const throttled = throttle(fn, 100)
      const ctx = { value: 42 }
      throttled.call(ctx, 'arg1', 'arg2')
      expect(fn).toHaveBeenCalledWith('arg1', 'arg2')
      expect(fn.mock.instances[0]).toBe(ctx)
    })
  })
})

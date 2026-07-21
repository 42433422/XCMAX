import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('./apiBase', () => ({
  apiFetch: vi.fn(),
  getApiBase: vi.fn(() => ''),
}))

vi.mock('./typeGuards', () => ({
  asRecord: (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {}),
  asString: (v: unknown) => (typeof v === 'string' ? v : ''),
}))

import { apiFetch } from './apiBase'
import {
  translateZhToEn,
  prefetchSubtitleTranslations,
  splitTtsSubtitleLines,
} from './ttsSubtitleTranslate'

// Unique counter to avoid cross-test cache hits
let uniqCounter = 0
const uniqZh = () => `测试-${++uniqCounter}-唯一`

describe('ttsSubtitleTranslate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('splitTtsSubtitleLines', () => {
    it('returns empty array for empty input', () => {
      expect(splitTtsSubtitleLines('')).toEqual([])
      expect(splitTtsSubtitleLines('   ')).toEqual([])
    })

    it('returns original text when no punctuation', () => {
      expect(splitTtsSubtitleLines('你好世界')).toEqual(['你好世界'])
    })

    it('splits by Chinese punctuation', () => {
      const result = splitTtsSubtitleLines('你好。世界！再见？')
      expect(result).toEqual(['你好。', '世界！', '再见？'])
    })

    it('splits by English punctuation', () => {
      const result = splitTtsSubtitleLines('Hello. World! Bye?')
      expect(result.length).toBe(3)
    })

    it('trims whitespace in parts', () => {
      const result = splitTtsSubtitleLines('你好 。 世界 ')
      expect(result.every((s) => s === s.trim())).toBe(true)
    })
  })

  describe('translateZhToEn', () => {
    it('returns empty for empty input', async () => {
      expect(await translateZhToEn('')).toBe('')
      expect(await translateZhToEn('   ')).toBe('')
    })

    it('returns original text if mostly English', async () => {
      const text = 'This is a long English sentence with many words'
      expect(await translateZhToEn(text)).toBe(text)
    })

    it('returns translation from API', async () => {
      const zh = uniqZh()
      ;(apiFetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, data: { translation: 'Hello world' } }),
      })
      const result = await translateZhToEn(zh)
      expect(result).toBe('Hello world')
    })

    it('returns empty when API response not ok', async () => {
      const zh = uniqZh()
      ;(apiFetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: false,
        json: async () => ({ success: false }),
      })
      const result = await translateZhToEn(zh)
      expect(result).toBe('')
    })

    it('returns empty when API throws', async () => {
      const zh = uniqZh()
      ;(apiFetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('network'))
      const result = await translateZhToEn(zh)
      expect(result).toBe('')
    })

    it('uses cached translation on subsequent calls', async () => {
      const zh = uniqZh()
      ;(apiFetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, data: { translation: 'Hello' } }),
      })
      await translateZhToEn(zh)
      const callsBefore = (apiFetch as ReturnType<typeof vi.fn>).mock.calls.length
      await translateZhToEn(zh)
      const callsAfter = (apiFetch as ReturnType<typeof vi.fn>).mock.calls.length
      expect(callsAfter).toBe(callsBefore)
    })

    it('falls back to data.text if data.translation is missing', async () => {
      const zh = uniqZh()
      ;(apiFetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, data: { text: 'Hello from text field' } }),
      })
      const result = await translateZhToEn(zh)
      expect(result).toBe('Hello from text field')
    })
  })

  describe('prefetchSubtitleTranslations', () => {
    it('calls onLine callback for each translated line', async () => {
      ;(apiFetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, data: { translation: 'translated' } }),
      })
      const onLine = vi.fn()
      prefetchSubtitleTranslations([uniqZh(), uniqZh()], onLine)
      await new Promise((resolve) => setTimeout(resolve, 50))
      expect(onLine).toHaveBeenCalledWith(0, 'translated')
      expect(onLine).toHaveBeenCalledWith(1, 'translated')
    })

    it('skips empty lines', async () => {
      const zh = uniqZh()
      ;(apiFetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, data: { translation: 'translated-unique' } }),
      })
      const onLine = vi.fn()
      prefetchSubtitleTranslations(['', zh], onLine)
      await new Promise((resolve) => setTimeout(resolve, 50))
      expect(onLine).toHaveBeenCalledTimes(1)
      expect(onLine).toHaveBeenCalledWith(1, 'translated-unique')
    })
  })
})

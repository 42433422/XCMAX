import { describe, it, expect, beforeEach, vi } from 'vitest'

import {
  beginTtsSubtitles,
  isTtsSubtitleSession,
  setTtsSubtitleIndex,
  updateTtsSubtitleEn,
  endTtsSubtitles,
  useTtsSubtitleStore,
} from './ttsSubtitleStore'

describe('ttsSubtitleStore', () => {
  beforeEach(() => {
    // Reset state between tests
    endTtsSubtitles()
  })

  describe('beginTtsSubtitles', () => {
    it('returns session gen and activates session with cleaned lines', () => {
      const gen = beginTtsSubtitles(['你好', '', '世界'])
      expect(typeof gen).toBe('number')
      const store = useTtsSubtitleStore()
      expect(store.visible.value).toBe(true)
      expect(store.lines.value.length).toBe(2) // empty line filtered out
    })

    it('hides subtitle when no lines after cleaning', () => {
      const gen = beginTtsSubtitles(['', '  ', ''])
      const store = useTtsSubtitleStore()
      expect(store.visible.value).toBe(false)
      expect(gen).toBeGreaterThan(0)
    })
  })

  describe('isTtsSubtitleSession', () => {
    it('returns true for current session gen while visible', () => {
      const gen = beginTtsSubtitles(['你好'])
      expect(isTtsSubtitleSession(gen)).toBe(true)
    })

    it('returns false after session ended', () => {
      const gen = beginTtsSubtitles(['你好'])
      endTtsSubtitles(gen)
      expect(isTtsSubtitleSession(gen)).toBe(false)
    })

    it('returns false for stale gen', () => {
      const gen1 = beginTtsSubtitles(['你好'])
      const gen2 = beginTtsSubtitles(['世界'])
      expect(isTtsSubtitleSession(gen1)).toBe(false)
      expect(isTtsSubtitleSession(gen2)).toBe(true)
    })
  })

  describe('setTtsSubtitleIndex', () => {
    it('updates currentIndex within bounds', () => {
      const gen = beginTtsSubtitles(['你好', '世界', '再见'])
      setTtsSubtitleIndex(2, gen)
      const store = useTtsSubtitleStore()
      expect(store.currentIndex.value).toBe(2)
    })

    it('clamps index to upper bound', () => {
      const gen = beginTtsSubtitles(['你好', '世界'])
      setTtsSubtitleIndex(100, gen)
      const store = useTtsSubtitleStore()
      expect(store.currentIndex.value).toBe(1)
    })

    it('clamps index to lower bound', () => {
      const gen = beginTtsSubtitles(['你好', '世界'])
      setTtsSubtitleIndex(-5, gen)
      const store = useTtsSubtitleStore()
      expect(store.currentIndex.value).toBe(0)
    })

    it('ignores stale gen', () => {
      const gen1 = beginTtsSubtitles(['你好', '世界'])
      const gen2 = beginTtsSubtitles(['新内容'])
      setTtsSubtitleIndex(0, gen1)
      const store = useTtsSubtitleStore()
      expect(store.currentIndex.value).toBe(0) // gen2 starts at 0
    })

    it('no-ops when not visible', () => {
      endTtsSubtitles()
      setTtsSubtitleIndex(5)
      const store = useTtsSubtitleStore()
      expect(store.currentIndex.value).toBe(0)
    })
  })

  describe('updateTtsSubtitleEn', () => {
    it('updates English text for a line', () => {
      const gen = beginTtsSubtitles(['你好', '世界'])
      updateTtsSubtitleEn(0, 'Hello', gen)
      const store = useTtsSubtitleStore()
      expect(store.lines.value[0].en).toBe('Hello')
    })

    it('trims English text', () => {
      const gen = beginTtsSubtitles(['你好'])
      updateTtsSubtitleEn(0, '  Hello  ', gen)
      const store = useTtsSubtitleStore()
      expect(store.lines.value[0].en).toBe('Hello')
    })

    it('ignores stale gen', () => {
      const gen1 = beginTtsSubtitles(['你好'])
      const gen2 = beginTtsSubtitles(['新内容'])
      updateTtsSubtitleEn(0, 'Hello', gen1)
      const store = useTtsSubtitleStore()
      expect(store.lines.value[0].en).toBe('')
    })

    it('no-ops for invalid index', () => {
      const gen = beginTtsSubtitles(['你好'])
      updateTtsSubtitleEn(99, 'Hello', gen)
      const store = useTtsSubtitleStore()
      expect(store.lines.value.length).toBe(1)
    })
  })

  describe('endTtsSubtitles', () => {
    it('hides subtitle and clears lines', () => {
      beginTtsSubtitles(['你好', '世界'])
      endTtsSubtitles()
      const store = useTtsSubtitleStore()
      expect(store.visible.value).toBe(false)
      expect(store.lines.value).toEqual([])
      expect(store.currentIndex.value).toBe(0)
    })

    it('dismiss callback ends subtitles', () => {
      beginTtsSubtitles(['你好'])
      const store = useTtsSubtitleStore()
      store.dismiss()
      expect(store.visible.value).toBe(false)
    })
  })

  describe('useTtsSubtitleStore', () => {
    it('computes current/prev/next line', () => {
      const gen = beginTtsSubtitles(['一', '二', '三'])
      setTtsSubtitleIndex(1, gen)
      const store = useTtsSubtitleStore()
      expect(store.current.value?.zh).toBe('二')
      expect(store.prev.value?.zh).toBe('一')
      expect(store.next.value?.zh).toBe('三')
    })

    it('returns null for prev at first index', () => {
      const gen = beginTtsSubtitles(['一', '二'])
      setTtsSubtitleIndex(0, gen)
      const store = useTtsSubtitleStore()
      expect(store.prev.value).toBeNull()
    })

    it('returns null for next at last index', () => {
      const gen = beginTtsSubtitles(['一', '二'])
      setTtsSubtitleIndex(1, gen)
      const store = useTtsSubtitleStore()
      expect(store.next.value).toBeNull()
    })

    it('returns null current when no lines', () => {
      endTtsSubtitles()
      const store = useTtsSubtitleStore()
      expect(store.current.value).toBeNull()
    })
  })
})

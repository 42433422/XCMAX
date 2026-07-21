import { describe, expect, it, beforeEach } from 'vitest'
import {
  beginTtsSubtitles,
  endTtsSubtitles,
  isTtsSubtitleSession,
  setTtsSubtitleIndex,
  updateTtsSubtitleEn,
  useTtsSubtitleStore,
} from './ttsSubtitleStore'

describe('ttsSubtitleStore', () => {
  beforeEach(() => {
    endTtsSubtitles()
  })

  it('begins session and advances index', () => {
    const gen = beginTtsSubtitles(['你好。', '我是小C。'])
    expect(isTtsSubtitleSession(gen)).toBe(true)
    const store = useTtsSubtitleStore()
    expect(store.visible.value).toBe(true)
    expect(store.current.value?.zh).toBe('你好。')
    setTtsSubtitleIndex(1, gen)
    expect(store.current.value?.zh).toBe('我是小C。')
  })

  it('updates english line', () => {
    const gen = beginTtsSubtitles(['你好。'])
    updateTtsSubtitleEn(0, 'Hello.', gen)
    const store = useTtsSubtitleStore()
    expect(store.current.value?.en).toBe('Hello.')
  })

  it('ends session', () => {
    const gen = beginTtsSubtitles(['你好。'])
    endTtsSubtitles(gen)
    expect(isTtsSubtitleSession(gen)).toBe(false)
    expect(useTtsSubtitleStore().visible.value).toBe(false)
  })
})

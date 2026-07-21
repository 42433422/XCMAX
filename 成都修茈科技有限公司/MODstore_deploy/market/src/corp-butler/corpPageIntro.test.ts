import { describe, it, expect, beforeEach } from 'vitest'
import {
  buildCorpPageIntroScript,
  isCorpProactiveIntroEnabled,
  setCorpProactiveIntroEnabled,
  CORP_PROACTIVE_INTRO_KEY,
} from './corpPageIntro'

describe('corpPageIntro', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('defaults proactive intro to enabled', () => {
    expect(isCorpProactiveIntroEnabled()).toBe(true)
  })

  it('persists toggle off/on', () => {
    setCorpProactiveIntroEnabled(false)
    expect(localStorage.getItem(CORP_PROACTIVE_INTRO_KEY)).toBe('0')
    expect(isCorpProactiveIntroEnabled()).toBe(false)
    setCorpProactiveIntroEnabled(true)
    expect(isCorpProactiveIntroEnabled()).toBe(true)
  })

  it('builds short 小C intro for home', () => {
    const { pageId, text } = buildCorpPageIntroScript('/index.html')
    expect(pageId).toBe('home')
    expect(text).toContain('小C')
    expect(text.length).toBeLessThanOrEqual(160)
  })

  it('builds intro for services page', () => {
    const { pageId, text } = buildCorpPageIntroScript('/services.html')
    expect(pageId).toBe('services')
    expect(text).toMatch(/产品|小C/)
  })
})

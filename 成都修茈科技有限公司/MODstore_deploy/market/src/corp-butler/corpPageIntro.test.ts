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

  it('builds short 小C intro for home without page context', () => {
    const { pageId, text } = buildCorpPageIntroScript('/index.html')
    expect(pageId).toBe('home')
    expect(text).toContain('小C')
    expect(text).not.toMatch(/你现在在|这页重点/)
    expect(text.length).toBeLessThanOrEqual(80)
  })

  it('builds same style intro for services page without page dump', () => {
    const { pageId, text } = buildCorpPageIntroScript('/services.html')
    expect(pageId).toBe('services')
    expect(text).toContain('小C')
    expect(text).not.toMatch(/你现在在|产品中心|这页重点/)
  })
})

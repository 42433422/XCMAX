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

  it('builds page-specific intro for home', () => {
    const { pageId, text } = buildCorpPageIntroScript('/index.html')
    expect(pageId).toBe('home')
    expect(text).toContain('小C')
    expect(text).toMatch(/XCAGI|行业 Mod|桌面/)
    expect(text).not.toMatch(/你现在在|这页重点/)
    expect(text.length).toBeLessThanOrEqual(140)
  })

  it('builds page-specific intro for download page', () => {
    const { pageId, text } = buildCorpPageIntroScript('/download')
    expect(pageId).toBe('download')
    expect(text).toContain('小C')
    expect(text).toMatch(/下载|安装包|macOS|Windows|Android/)
    expect(text).not.toMatch(/你现在在/)
  })

  it('builds page-specific intro for services page', () => {
    const { pageId, text } = buildCorpPageIntroScript('/services.html')
    expect(pageId).toBe('services')
    expect(text).toContain('小C')
    expect(text).toMatch(/产品|Excel|单据|MODstore|标签/)
    expect(text).not.toMatch(/你现在在/)
  })
})

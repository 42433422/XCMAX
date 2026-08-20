import { afterEach, describe, it, expect, beforeEach, vi } from 'vitest'
import {
  buildCorpPageIntroScript,
  hasIntroducedPageThisSession,
  isCorpProactiveIntroEnabled,
  markPageIntroduced,
  prefersReducedMotion,
  setCorpProactiveIntroEnabled,
  speakCorpIntro,
  stopCorpIntroSpeech,
  CORP_PROACTIVE_INTRO_KEY,
} from './corpPageIntro'

describe('corpPageIntro', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    )
  })

  afterEach(() => {
    stopCorpIntroSpeech()
    vi.unstubAllGlobals()
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

  it('tracks pages for the current session and reads reduced-motion preference', () => {
    expect(hasIntroducedPageThisSession('home')).toBe(false)
    markPageIntroduced('home')
    expect(hasIntroducedPageThisSession('home')).toBe(true)
    expect(prefersReducedMotion()).toBe(false)
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    )
    expect(prefersReducedMotion()).toBe(true)
  })

  it('fetches and plays sentence-aligned TTS while tolerating invalid responses', async () => {
    const play = vi.fn(function (this: { onended: ((event: Event) => void) | null }) {
      queueMicrotask(() => this.onended?.(new Event('ended')))
      return Promise.resolve()
    })
    class FakeAudio {
      onended: ((event: Event) => void) | null = null
      onerror: ((event: Event) => void) | null = null
      pause = vi.fn()
      removeAttribute = vi.fn()
      load = vi.fn()
      play = play
      constructor(public src: string) {}
    }
    vi.stubGlobal('Audio', FakeAudio)
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              data: { audioBase64: 'data:audio/mpeg;base64,QQ==' },
            }),
            { status: 200 },
          ),
        )
        .mockResolvedValueOnce(new Response('not-json', { status: 200 })),
    )

    await speakCorpIntro('第一句介绍内容较长。第二句介绍内容也较长。')
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(play).toHaveBeenCalledOnce()
    stopCorpIntroSpeech()
  })

  it('short-circuits empty, reduced-motion and failed TTS responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{}', { status: 503 })),
    )
    await speakCorpIntro('')
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    )
    await speakCorpIntro('不会朗读')
    expect(fetch).not.toHaveBeenCalled()

    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    )
    await speakCorpIntro('服务失败也不阻断页面')
    expect(fetch).toHaveBeenCalledOnce()
  })
})

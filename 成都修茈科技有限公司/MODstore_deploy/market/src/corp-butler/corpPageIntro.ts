/** 官网小C：同意后主动介绍当前页（TTS + 中文字幕）。软件工作台不挂字幕。 */

import { getCorpPageKnowledge, resolveCorpPageId } from '../content/siteKnowledge'
import { beginTtsSubtitles, endTtsSubtitles, isTtsSubtitleSession, setTtsSubtitleIndex } from '../composables/ttsSubtitleStore'
import { splitSentences } from '../utils/ttsSentenceSplit'
import { cleanTextForTts } from '../utils/ttsTextClean'

export const CORP_PROACTIVE_INTRO_KEY = 'xc_corp_proactive_intro'
const SESSION_PREFIX = 'xc-corp-intro-done:'
const CORP_TTS_PATH = '/api/agent/butler/corp-tts'

export function isCorpProactiveIntroEnabled(): boolean {
  try {
    const v = localStorage.getItem(CORP_PROACTIVE_INTRO_KEY)
    if (v === '0' || v === 'false') return false
    return true
  } catch {
    return true
  }
}

export function setCorpProactiveIntroEnabled(on: boolean): void {
  try {
    localStorage.setItem(CORP_PROACTIVE_INTRO_KEY, on ? '1' : '0')
  } catch {
    // ignore
  }
}

export function hasIntroducedPageThisSession(pageId: string): boolean {
  try {
    return sessionStorage.getItem(SESSION_PREFIX + pageId) === '1'
  } catch {
    return false
  }
}

export function markPageIntroduced(pageId: string): void {
  try {
    sessionStorage.setItem(SESSION_PREFIX + pageId, '1')
  } catch {
    // ignore
  }
}

function clip(text: string, max: number): string {
  const t = (text || '').replace(/\s+/g, ' ').trim()
  if (t.length <= max) return t
  return `${t.slice(0, Math.max(0, max - 1))}…`
}

/** 生成适合朗读的短介绍：按当前页说清「这页是什么」，不堆「你现在在…」元叙述。 */
export function buildCorpPageIntroScript(pathname: string): {
  pageId: string
  text: string
} {
  const pageId = resolveCorpPageId(pathname)
  const page = getCorpPageKnowledge(pageId, pathname)
  const body = clip(page.summary || page.welcomeDesc || '', 72)
  const text = clip(
    body ? `嗨，我是小C。${body}有需要直接问我，或点快捷问题。` : '嗨，我是小C。想了解产品、案例或预约沟通，直接跟我说，或点快捷问题就行。',
    140,
  )
  return { pageId, text }
}

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

let corpIntroAudio: HTMLAudioElement | null = null
let corpSubtitleGen = 0

export function stopCorpIntroSpeech(): void {
  if (typeof window === 'undefined') return
  if (corpIntroAudio) {
    try {
      corpIntroAudio.pause()
      corpIntroAudio.removeAttribute('src')
      corpIntroAudio.load()
    } catch {
      // ignore
    }
    corpIntroAudio = null
  }
  endTtsSubtitles(corpSubtitleGen)
}

async function fetchCorpTtsDataUri(text: string): Promise<string | null> {
  const res = await fetch(CORP_TTS_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ text }),
    credentials: 'same-origin',
  })
  if (!res.ok) return null
  let json: Record<string, unknown> = {}
  try {
    json = (await res.json()) as Record<string, unknown>
  } catch {
    return null
  }
  const data = (json.data && typeof json.data === 'object' ? json.data : json) as Record<string, unknown>
  const uri = data.audioBase64
  return typeof uri === 'string' && uri.startsWith('data:') ? uri : null
}

function playDataUri(uri: string, gen: number): Promise<void> {
  return new Promise((resolve) => {
    if (!isTtsSubtitleSession(gen)) {
      resolve()
      return
    }
    const a = new Audio(uri)
    corpIntroAudio = a
    const done = () => {
      if (corpIntroAudio === a) corpIntroAudio = null
      resolve()
    }
    a.onended = done
    a.onerror = done
    void a.play().catch(done)
  })
}

/** 服务端 MiMo → Edge 神经音；失败静默，不回退系统 TTS。按句合成以音画同步。 */
export function speakCorpIntro(text: string): Promise<void> {
  if (typeof window === 'undefined' || !text.trim()) return Promise.resolve()
  if (prefersReducedMotion()) return Promise.resolve()

  stopCorpIntroSpeech()
  // 朗读/字幕共用清洗：去掉网址、路径、装饰符，避免念出 slash、html、箭头
  const plain = cleanTextForTts(text, 800)
  if (!plain) return Promise.resolve()
  const lines = splitSentences(plain)
  const zhLines = lines.length ? lines : [plain]
  corpSubtitleGen = beginTtsSubtitles(zhLines)
  const gen = corpSubtitleGen
  setTtsSubtitleIndex(0, gen)

  return (async () => {
    try {
      // 按句请求 TTS：当前句字幕与该句音频一一对应，避免整段均分导致不同步
      const prefetch = new Map<number, Promise<string | null>>()
      const ensure = (i: number) => {
        if (!prefetch.has(i)) prefetch.set(i, fetchCorpTtsDataUri(zhLines[i]!))
        return prefetch.get(i)!
      }
      // 预取首句 + 下一句
      void ensure(0)
      if (zhLines.length > 1) void ensure(1)

      for (let i = 0; i < zhLines.length; i += 1) {
        if (!isTtsSubtitleSession(gen)) return
        setTtsSubtitleIndex(i, gen)
        if (i + 1 < zhLines.length) void ensure(i + 1)
        const uri = await ensure(i)
        if (!uri || !isTtsSubtitleSession(gen)) continue
        await playDataUri(uri, gen)
      }
    } catch {
      // fail-open：不使用 speechSynthesis
    } finally {
      endTtsSubtitles(gen)
    }
  })()
}

/** 官网小C：同意后主动介绍当前页（TTS + 文案）。 */

import { getCorpPageKnowledge, resolveCorpPageId } from '../content/siteKnowledge'

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

/** 生成适合朗读的短介绍（控制在约 160 字内）。 */
export function buildCorpPageIntroScript(pathname: string): {
  pageId: string
  text: string
} {
  const pageId = resolveCorpPageId(pathname)
  const page = getCorpPageKnowledge(pageId)
  const title = clip((page.title || '').split('|')[0] || page.pageId, 24)
  const summary = clip(page.summary || page.description || '', 72)
  const highlights = (page.highlights || []).slice(0, 2).join('、')
  const hi = highlights ? clip(`这页重点：${highlights}。`, 40) : ''
  const text = clip(
    `嗨，我是小C。你现在在「${title}」。${summary}${hi ? ` ${hi}` : ''} 想细聊直接跟我说，或点快捷问题就行。`,
    160,
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

/** 服务端 MiMo → Edge 神经音；失败静默，不回退系统 TTS。 */
export function speakCorpIntro(text: string): Promise<void> {
  if (typeof window === 'undefined' || !text.trim()) return Promise.resolve()
  if (prefersReducedMotion()) return Promise.resolve()

  stopCorpIntroSpeech()
  return (async () => {
    try {
      const uri = await fetchCorpTtsDataUri(text.trim())
      if (!uri) return
      await new Promise<void>((resolve) => {
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
    } catch {
      // fail-open：不使用 speechSynthesis
    }
  })()
}

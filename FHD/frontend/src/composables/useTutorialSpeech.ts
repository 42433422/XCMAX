import { apiFetch } from '@/utils/apiBase'
import { readCsrfTokenFromCookie } from '@/utils/csrfCookie'

const TTS_CACHE_MAX = 80
const SPEECH_END_PADDING_MS = 450
const PREFETCH_MAX_CONCURRENT = 2

export type TutorialSpeechBundle = {
  uri: string
  durationMs: number
}

export type TutorialSpeechController = {
  speak: (text: string) => Promise<void>
  stop: () => void
  prefetch: (texts: string[]) => void
  prefetchAll: (texts: string[]) => Promise<void>
  getCachedDuration: (text: string) => number
  stepHoldMs: (text: string, baseDurationMs: number) => number
}

let sharedTutorialSpeech: TutorialSpeechController | null = null

export function getTutorialSpeech(): TutorialSpeechController {
  if (!sharedTutorialSpeech) {
    sharedTutorialSpeech = createTutorialSpeech()
  }
  return sharedTutorialSpeech
}

export function createTutorialSpeech(): TutorialSpeechController {
  let generation = 0
  let ttsAudio: HTMLAudioElement | null = null
  const ttsCache = new Map<string, TutorialSpeechBundle>()
  const ttsInflight = new Map<string, Promise<TutorialSpeechBundle | null>>()
  let prefetchSlots = 0
  const prefetchPending: string[] = []

  const stopPlayback = () => {
    if (ttsAudio) {
      try {
        ttsAudio.pause()
        ttsAudio.src = ''
      } catch {
        /* ignore */
      }
      ttsAudio = null
    }
  }

  const stop = () => {
    generation += 1
    stopPlayback()
  }

  const setCache = (text: string, bundle: TutorialSpeechBundle) => {
    if (ttsCache.has(text)) ttsCache.delete(text)
    ttsCache.set(text, bundle)
    if (ttsCache.size > TTS_CACHE_MAX) {
      const oldest = ttsCache.keys().next().value
      if (oldest) ttsCache.delete(oldest)
    }
  }

  const measureDurationMs = (uri: string) =>
    new Promise<number>((resolve) => {
      const audio = new Audio()
      const done = (ms: number) => {
        audio.src = ''
        resolve(ms)
      }
      audio.addEventListener('loadedmetadata', () => {
        const sec = Number(audio.duration)
        done(Number.isFinite(sec) && sec > 0 ? Math.ceil(sec * 1000) : 0)
      })
      audio.addEventListener('error', () => done(0))
      audio.src = uri
    })

  const fetchTtsBundle = async (text: string): Promise<TutorialSpeechBundle | null> => {
    const content = String(text || '').trim()
    if (!content) return null
    if (ttsCache.has(content)) return ttsCache.get(content) || null
    if (ttsInflight.has(content)) return ttsInflight.get(content) || null

    const req = (async () => {
      await ensureTutorialTtsCsrfCookie()

      const resp = await apiFetch('/api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        timeoutMs: 30_000,
        body: JSON.stringify({
          text: content,
          lang: 'zh',
          voice: 'zh-CN-XiaoxiaoNeural',
        }),
      })
      const data = await resp.json().catch(() => ({}))
      const uri = data?.data?.audioBase64
      if (
        !resp.ok ||
        !data?.success ||
        typeof uri !== 'string' ||
        !uri.startsWith('data:audio/')
      ) {
        return null
      }
      const durationMs = await measureDurationMs(uri)
      const bundle = { uri, durationMs }
      setCache(content, bundle)
      return bundle
    })()
      .catch(() => null)
      .finally(() => {
        ttsInflight.delete(content)
      })

    ttsInflight.set(content, req)
    return req
  }

  const drainPrefetch = () => {
    while (prefetchSlots < PREFETCH_MAX_CONCURRENT && prefetchPending.length) {
      const t = prefetchPending.shift()
      if (!t || ttsCache.has(t) || ttsInflight.has(t)) continue
      prefetchSlots += 1
      fetchTtsBundle(t).finally(() => {
        prefetchSlots -= 1
        drainPrefetch()
      })
    }
  }

  const prefetch = (texts: string[]) => {
    for (const raw of texts) {
      const t = String(raw || '').trim()
      if (!t || ttsCache.has(t) || ttsInflight.has(t) || prefetchPending.includes(t)) continue
      prefetchPending.push(t)
    }
    drainPrefetch()
  }

  const prefetchAll = async (texts: string[]) => {
    const unique = [...new Set(texts.map((t) => String(t || '').trim()).filter(Boolean))]
    prefetch(unique)
    await Promise.all(unique.map((t) => fetchTtsBundle(t)))
  }

  const getCachedDuration = (text: string) => {
    const content = String(text || '').trim()
    if (!content) return 0
    return ttsCache.get(content)?.durationMs || 0
  }

  const stepHoldMs = (text: string, baseDurationMs: number) => {
    const speechMs = getCachedDuration(text)
    const padded = speechMs > 0 ? speechMs + SPEECH_END_PADDING_MS : 0
    return Math.max(baseDurationMs, padded)
  }

  const speak = async (text: string) => {
    const content = String(text || '').trim()
    if (!content) return
    const myGen = ++generation
    stopPlayback()

    const bundle = (await fetchTtsBundle(content)) || ttsCache.get(content) || null
    if (!bundle || myGen !== generation) return

    await new Promise<void>((resolve) => {
      const audio = new Audio(bundle.uri)
      ttsAudio = audio
      const finish = () => {
        if (ttsAudio === audio) ttsAudio = null
        resolve()
      }
      audio.addEventListener('ended', finish, { once: true })
      audio.addEventListener('error', finish, { once: true })
      if (myGen !== generation) {
        finish()
        return
      }
      void audio.play().catch(() => finish())
    })
  }

  return {
    speak,
    stop,
    prefetch,
    prefetchAll,
    getCachedDuration,
    stepHoldMs,
  }
}

async function ensureTutorialTtsCsrfCookie(): Promise<void> {
  if (typeof window === 'undefined') return
  if (readCsrfTokenFromCookie()) return
  try {
    await apiFetch('/api/health', { method: 'GET', timeoutMs: 5_000 })
  } catch {
    /* best-effort: the following POST will surface the actual TTS error */
  }
}

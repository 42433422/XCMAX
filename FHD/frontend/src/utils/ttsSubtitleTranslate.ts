import { apiFetch } from './apiBase'
import { asRecord, asString } from '@/utils/typeGuards'

const CACHE_MAX = 80
const cache = new Map<string, string>()

function looksMostlyEnglish(text: string): boolean {
  const t = text.trim()
  if (!t) return true
  const latin = (t.match(/[A-Za-z]/g) || []).length
  const cjk = (t.match(/[\u4e00-\u9fff]/g) || []).length
  return latin >= 8 && latin > cjk * 2
}

export async function translateZhToEn(text: string): Promise<string> {
  const zh = String(text || '').trim()
  if (!zh) return ''
  if (looksMostlyEnglish(zh)) return zh
  const hit = cache.get(zh)
  if (hit) return hit

  try {
    const res = await apiFetch('/api/tts/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      timeoutMs: 20_000,
      body: JSON.stringify({ text: zh.slice(0, 500), target: 'en' }),
    })
    const json = asRecord(await res.json())
    if (!res.ok || !json.success) return ''
    const data = asRecord(json.data)
    const en = asString(data.translation) || asString(data.text) || ''
    if (!en) return ''
    cache.set(zh, en)
    while (cache.size > CACHE_MAX) {
      const first = cache.keys().next().value
      if (first === undefined) break
      cache.delete(first)
    }
    return en
  } catch {
    return ''
  }
}

export function prefetchSubtitleTranslations(
  zhLines: string[],
  onLine: (index: number, en: string) => void,
): void {
  void (async () => {
    for (let i = 0; i < zhLines.length; i++) {
      const zh = zhLines[i]
      if (!zh) continue
      const en = await translateZhToEn(zh)
      if (en) onLine(i, en)
    }
  })()
}

/** 按中文标点粗分句，供字幕推进。 */
export function splitTtsSubtitleLines(text: string): string[] {
  const t = String(text || '').trim()
  if (!t) return []
  const parts = t
    .split(/(?<=[。！？；.!?;])\s*/)
    .map((s) => s.trim())
    .filter(Boolean)
  return parts.length ? parts : [t]
}

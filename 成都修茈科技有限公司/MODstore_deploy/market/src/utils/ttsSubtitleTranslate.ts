/** 朗读字幕：中文 → 英文（短句缓存 + 公开 corp-translate）。 */

const CACHE_MAX = 80
const cache = new Map<string, string>()
const TRANSLATE_PATH = '/api/agent/butler/corp-translate'

function cacheGet(zh: string): string | undefined {
  return cache.get(zh)
}

function cacheSet(zh: string, en: string): void {
  cache.set(zh, en)
  while (cache.size > CACHE_MAX) {
    const first = cache.keys().next().value
    if (first === undefined) break
    cache.delete(first)
  }
}

/** 已是英文为主则原样返回，避免二次翻译。 */
function looksMostlyEnglish(text: string): boolean {
  const t = text.trim()
  if (!t) return true
  const latin = (t.match(/[A-Za-z]/g) || []).length
  const cjk = (t.match(/[\u4e00-\u9fff]/g) || []).length
  return latin >= 8 && latin > cjk * 2
}

export async function translateZhToEn(text: string, signal?: AbortSignal): Promise<string> {
  const zh = String(text || '').trim()
  if (!zh) return ''
  if (looksMostlyEnglish(zh)) return zh
  const hit = cacheGet(zh)
  if (hit) return hit

  try {
    const res = await fetch(TRANSLATE_PATH, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ text: zh.slice(0, 500), target: 'en' }),
      credentials: 'same-origin',
      signal,
    })
    if (!res.ok) return ''
    const json = (await res.json()) as Record<string, unknown>
    const data = json.data && typeof json.data === 'object' ? (json.data as Record<string, unknown>) : json
    const en = String(data.translation || data.text || data.en || '').trim()
    if (!en) return ''
    cacheSet(zh, en)
    return en
  } catch {
    return ''
  }
}

/** 预取多句英文，按序写回字幕 store。 */
export function prefetchSubtitleTranslations(
  zhLines: string[],
  onLine: (index: number, en: string) => void,
  opts?: { signal?: AbortSignal; concurrency?: number },
): void {
  const concurrency = Math.max(1, opts?.concurrency ?? 2)
  let cursor = 0

  const worker = async () => {
    while (cursor < zhLines.length) {
      if (opts?.signal?.aborted) return
      const i = cursor
      cursor += 1
      const zh = zhLines[i]
      if (!zh) continue
      const en = await translateZhToEn(zh, opts?.signal)
      if (opts?.signal?.aborted) return
      if (en) onLine(i, en)
    }
  }

  void Promise.all(Array.from({ length: concurrency }, () => worker()))
}

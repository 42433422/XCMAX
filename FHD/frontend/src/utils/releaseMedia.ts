/** Cursor-style update card media: poster required, short video optional. */

export interface ReleaseMediaSlide {
  posterUrl: string
  videoUrl?: string
  caption?: string
}

const MAX_SLIDES = 8

export function isSafeMediaUrl(raw: unknown): raw is string {
  const url = String(raw || '').trim()
  if (!url || url.length > 2048) return false
  try {
    const parsed = new URL(url)
    if (parsed.protocol === 'https:') return true
    if (parsed.protocol === 'http:' && /^(localhost|127\.0\.0\.1|\[::1\])$/i.test(parsed.hostname)) {
      return true
    }
    return false
  } catch {
    return false
  }
}

export function normalizeReleaseMedia(input: unknown): ReleaseMediaSlide[] {
  const items: unknown[] = Array.isArray(input) ? input : input && typeof input === 'object' ? [input] : []
  const slides: ReleaseMediaSlide[] = []
  for (const item of items) {
    if (!item || typeof item !== 'object') continue
    const row = item as Record<string, unknown>
    const posterUrl = String(row.posterUrl || row.poster || '').trim()
    if (!isSafeMediaUrl(posterUrl)) continue
    const videoRaw = String(row.videoUrl || row.video || '').trim()
    const videoUrl = isSafeMediaUrl(videoRaw) ? videoRaw : undefined
    const caption = String(row.caption || row.title || '')
      .trim()
      .slice(0, 120)
    slides.push({
      posterUrl,
      ...(videoUrl ? { videoUrl } : {}),
      ...(caption ? { caption } : {}),
    })
    if (slides.length >= MAX_SLIDES) break
  }
  return slides
}

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
    // 本机/内网联调允许 http
    if (parsed.protocol === 'http:' && /^(localhost|127\.0\.0\.1|\[::1\])$/i.test(parsed.hostname)) {
      return true
    }
    return false
  } catch {
    return false
  }
}

export function normalizeReleaseMedia(input: unknown): ReleaseMediaSlide[] {
  const items: unknown[] = Array.isArray(input)
    ? input
    : input && typeof input === 'object'
      ? [input]
      : []
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

/**
 * 从 latest.yml 文本解析 releaseMedia（列表或单对象）。
 * 不依赖完整 YAML 库，仅覆盖发版脚本写出的缩进形态。
 */
export function parseReleaseMediaFromYaml(content: string): ReleaseMediaSlide[] {
  const lines = content.split(/\r?\n/)
  const start = lines.findIndex(line => line.startsWith('releaseMedia:'))
  if (start < 0) return []

  const head = lines[start].slice('releaseMedia:'.length).trim()
  if (head && head !== '|' && head !== '>') {
    // 不允许内联 JSON；留空走块解析
  }

  const block: string[] = []
  for (let i = start + 1; i < lines.length; i += 1) {
    const line = lines[i]
    if (!line.startsWith(' ') && !line.startsWith('\t') && line.trim() !== '') break
    if (line.startsWith('signature:')) break
    block.push(line)
  }
  if (!block.length) return []

  const slides: Array<Record<string, string>> = []
  let current: Record<string, string> | null = null

  const fieldRe = /^\s+(posterUrl|videoUrl|caption|poster|video|title):\s*(.*)$/
  for (const line of block) {
    if (/^\s*-\s+/.test(line)) {
      current = {}
      slides.push(current)
      const inline = line.replace(/^\s*-\s+/, '')
      const m = inline.match(/^(posterUrl|videoUrl|caption|poster|video|title):\s*(.*)$/)
      if (m) {
        current[m[1]] = stripQuotes(m[2])
      }
      continue
    }
    const m = line.match(fieldRe)
    if (!m) continue
    if (!current) {
      current = {}
      slides.push(current)
    }
    current[m[1]] = stripQuotes(m[2])
  }

  return normalizeReleaseMedia(slides)
}

function stripQuotes(value: string): string {
  const v = value.trim()
  if (
    (v.startsWith('"') && v.endsWith('"')) ||
    (v.startsWith("'") && v.endsWith("'"))
  ) {
    return v.slice(1, -1)
  }
  return v
}

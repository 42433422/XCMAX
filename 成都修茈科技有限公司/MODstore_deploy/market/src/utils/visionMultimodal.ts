/**
 * OpenAI-compatible chat multimodal parts + image compression for vision-in (VLM) flows.
 */

import type { LlmProviderBlock } from '../composables/llmCatalogModelHelpers'

export type OpenAiVisionPart =
  | { type: 'text'; text: string }
  | { type: 'image_url'; image_url: { url: string } }

const VISION_HINT_RE =
  /vision|vl-|vlm|deepseek-vl|qwen-vl|llava|omni|gpt-4o|gpt-4\.1|gpt-4-turbo|gemini-1\.5|gemini-2|claude-3|claude-sonnet|claude-opus|4k图|多模态/i

export function modelSupportsVisionInput(
  provider: string,
  model: string,
  catalog: { providers?: LlmProviderBlock[] } | null | undefined,
): boolean {
  const m = String(model || '').trim()
  const p = String(provider || '').trim()
  if (!m) return false
  const block = catalog?.providers?.find((x) => x.provider === p)
  const detailed = block?.models_detailed
  if (detailed && detailed.length) {
    const row = detailed.find((r) => r.id === m)
    if (row?.category === 'vlm') return true
  }
  if (VISION_HINT_RE.test(m)) return true
  return false
}

export function flattenTextForLlmContext(text: string, parts: OpenAiVisionPart[] | undefined): string {
  if (parts && parts.length) {
    const t = parts.filter((x): x is { type: 'text'; text: string } => x.type === 'text').map((x) => x.text)
    return [text, ...t].filter(Boolean).join('\n')
  }
  return text
}

/**
 * Downscale & re-encode as JPEG to stay under maxBytes (approximate).
 */
export async function compressImageFileToDataUrl(
  file: File,
  opts?: { maxEdge?: number; maxBytes?: number; mime?: string },
): Promise<string> {
  const maxEdge = Math.max(256, Math.min(4096, Number(opts?.maxEdge ?? 2048)))
  const maxBytes = Math.max(256 * 1024, Math.min(20 * 1024 * 1024, Number(opts?.maxBytes ?? 5 * 1024 * 1024)))
  const preferMime = opts?.mime === 'image/png' ? 'image/png' : 'image/jpeg'

  const bitmap = await createImageBitmap(file)
  try {
    let { width, height } = bitmap
    const scale = Math.min(1, maxEdge / Math.max(width, height))
    const tw = Math.max(1, Math.round(width * scale))
    const th = Math.max(1, Math.round(height * scale))
    const canvas = document.createElement('canvas')
    canvas.width = tw
    canvas.height = th
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('canvas unsupported')
    ctx.drawImage(bitmap, 0, 0, tw, th)

    let quality = 0.92
    let dataUrl = canvas.toDataURL(preferMime, quality)
    let guard = 0
    while (dataUrl.length > maxBytes * 1.37 && quality > 0.35 && guard < 14) {
      quality -= 0.07
      guard += 1
      dataUrl = canvas.toDataURL('image/jpeg', quality)
    }
    if (dataUrl.length > maxBytes * 1.37) {
      throw new Error('图片压缩后仍过大，请换一张较小的图片或缩短边长')
    }
    return dataUrl
  } finally {
    bitmap.close()
  }
}

export function buildUserMultimodalContent(
  text: string,
  imageDataUrls: string[],
): string | OpenAiVisionPart[] {
  const t = String(text || '').trim()
  const urls = (imageDataUrls || []).filter((u) => typeof u === 'string' && u.trim())
  if (!urls.length) return t
  const parts: OpenAiVisionPart[] = []
  if (t) parts.push({ type: 'text', text: t })
  for (const url of urls) {
    parts.push({ type: 'image_url', image_url: { url: url.trim() } })
  }
  if (parts.length === 1 && parts[0].type === 'text') return parts[0].text
  return parts
}

export function isImageFileForVision(file: File): boolean {
  const mime = String(file.type || '')
  if (mime.startsWith('image/')) return true
  const name = file.name || ''
  const i = name.lastIndexOf('.')
  const ext = i >= 0 ? name.slice(i + 1).toLowerCase() : ''
  return ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'].includes(ext)
}

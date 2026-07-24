/**
 * Resolve a displayable image URL from a 客来来 / Kellai conversation message.
 */

export type KellaiMediaMessageLike = {
  content?: string
  content_type?: string
  metadata?: Record<string, unknown> | null
}

const META_URL_KEYS = [
  'media_url',
  'image_url',
  'pic_url',
  'PicUrl',
  'url',
  'src',
  'imageUrl',
  'mediaUrl',
] as const

function isRenderableImageUrl(value: string): boolean {
  const s = String(value || '').trim()
  if (!s || s.startsWith('[')) return false
  if (/^(data:image\/|blob:)/i.test(s)) return true
  if (!/^https?:\/\//i.test(s)) return false
  if (/\.(?:png|jpe?g|gif|webp|bmp|svg)(?:\?|#|$)/i.test(s)) return true
  // WeChat / channel CDNs often omit file extensions
  return true
}

export function resolveKellaiMessageImageSrc(message: KellaiMediaMessageLike | null | undefined): string {
  if (!message) return ''
  const meta =
    message.metadata && typeof message.metadata === 'object' ? message.metadata : {}
  for (const key of META_URL_KEYS) {
    const candidate = String(meta[key] ?? '').trim()
    if (isRenderableImageUrl(candidate)) return candidate
  }
  const content = String(message.content || '').trim()
  const contentType = String(message.content_type || '').toLowerCase()
  const typedImage = contentType.includes('image') || contentType === 'img'
  if (typedImage && isRenderableImageUrl(content)) return content
  if (/^(data:image\/|blob:)/i.test(content)) return content
  if (/\.(?:png|jpe?g|gif|webp|bmp|svg)(?:\?|#|$)/i.test(content) && /^https?:\/\//i.test(content)) {
    return content
  }
  return ''
}

export function isKellaiImagePlaceholder(content: string): boolean {
  return /^\[?\s*图片\s*\]?$/i.test(String(content || '').trim()) ||
    /^\[image\]$/i.test(String(content || '').trim())
}

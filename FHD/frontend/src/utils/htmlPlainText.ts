const OMITTED_TEXT_TAGS = new Set([
  'SCRIPT',
  'STYLE',
  'TEMPLATE',
  'NOSCRIPT',
  'IFRAME',
  'OBJECT',
  'EMBED',
])

function collectVisibleText(node: Node): string {
  if (node.nodeType === 3) return node.nodeValue || ''
  if (node.nodeType !== 1 && node.nodeType !== 9 && node.nodeType !== 11) return ''

  if (node.nodeType === 1) {
    const tagName = (node as Element).tagName
    if (tagName === 'BR') return '\n'
    if (OMITTED_TEXT_TAGS.has(tagName)) return ''
  }

  return Array.from(node.childNodes, collectVisibleText).join('')
}

function decodeCommonEntities(value: string): string {
  return value
    .replace(/&(nbsp|#160);/gi, ' ')
    .replace(/&quot;|&#34;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&')
}

/**
 * Convert HTML-like chat content to inert plain text.
 *
 * DOMParser keeps markup inert and avoids regex-based tag sanitization, which
 * is unsafe for malformed or nested markup. The scanner is only a non-DOM
 * fallback for tests/SSR and never returns markup as executable HTML.
 */
export function plainTextFromHtml(raw: unknown): string {
  const source = String(raw || '')
  if (!source) return ''

  if (typeof DOMParser !== 'undefined') {
    const document = new DOMParser().parseFromString(source, 'text/html')
    return collectVisibleText(document.body).replace(/\u00a0/g, ' ')
  }

  let result = ''
  let cursor = 0
  while (cursor < source.length) {
    const tagStart = source.indexOf('<', cursor)
    if (tagStart < 0) {
      result += source.slice(cursor)
      break
    }
    result += source.slice(cursor, tagStart)
    const tagEnd = source.indexOf('>', tagStart + 1)
    if (tagEnd < 0) {
      result += source.slice(tagStart)
      break
    }
    const tag = source.slice(tagStart + 1, tagEnd).trim().toLowerCase()
    if (tag === 'br' || tag === 'br/' || tag.startsWith('br ')) result += '\n'
    cursor = tagEnd + 1
  }
  return decodeCommonEntities(result)
}

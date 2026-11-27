/**
 * v-html 统一消毒入口（DOMPurify）。禁止在模板中写 v-html="原始字符串"。
 */
import DOMPurify, { type Config, type UponSanitizeAttributeHookEvent } from 'dompurify'
import { renderMarkdown, stripInternalMarkers } from '@/utils/lightMarkdown'

const CHAT_BUBBLE_CONFIG: Config = {
  ALLOWED_TAGS: [
    'a',
    'abbr',
    'b',
    'br',
    'blockquote',
    'caption',
    'code',
    'col',
    'colgroup',
    'div',
    'em',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'hr',
    'i',
    'li',
    'ol',
    'p',
    'pre',
    'span',
    'strong',
    'sub',
    'sup',
    'table',
    'tbody',
    'td',
    'tfoot',
    'th',
    'thead',
    'tr',
    'ul',
    'del',
    'ins',
    'kbd',
    'mark',
    'small',
    'time',
  ],
  ALLOWED_ATTR: [
    'href',
    'title',
    'target',
    'rel',
    'class',
    'id',
    'name',
    'colspan',
    'rowspan',
    'headers',
    'scope',
    'align',
    'width',
    'height',
    'lang',
    'dir',
    'style',
    'hidden',
    'aria-hidden',
  ],
  ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|[^a-z]|[a-z+.-]+(?:[^a-z+.\-:]|$))/i,
}

// Plain model text can contain markup-shaped tokens (for example a C++ header).
// A historical HTML fragment has a chat formatting tag with a closing tag or a line break.
const CHAT_HTML_FRAGMENT = /<br\s*\/?>|<\/(?:a|b|blockquote|code|div|em|h[1-6]|i|li|ol|p|pre|span|strong|table|td|th|tr|ul)>/i
const FENCED_CHAT_CODE = /(^|\n)(```[^\n]*\n[\s\S]*?(?:\n```(?=\n|$)|(?![\s\S])))/g

function mapOutsideChatCode(text: string, transform: (text: string) => string, code = (text: string) => text): string {
  let from = 0
  let result = ''
  for (const match of text.matchAll(FENCED_CHAT_CODE)) {
    const codeStart = (match.index ?? 0) + match[1].length
    result += transform(text.slice(from, codeStart)) + code(match[2])
    from = codeStart + match[2].length
  }
  return result + transform(text.slice(from))
}

export function normalizeServerContentToHtml(raw: unknown): string {
  const text = String(raw ?? '')
  if (CHAT_HTML_FRAGMENT.test(mapOutsideChatCode(text, prose => prose.replace(/`+[^`\n]*`+/g, ''), () => ''))) return text
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML.replace(/\r\n?|\n/g, '<br>')
}

/** AI 气泡：Markdown → HTML 后再消毒；允许代码块复制按钮与图片等 Markdown 产物 */
const CHAT_MARKDOWN_CONFIG: Config = {
  ...CHAT_BUBBLE_CONFIG,
  ALLOWED_TAGS: [...(CHAT_BUBBLE_CONFIG.ALLOWED_TAGS as string[]), 'img', 'button'],
  ALLOWED_ATTR: [
    ...(CHAT_BUBBLE_CONFIG.ALLOWED_ATTR as string[]),
    'src',
    'alt',
    'type',
    'data-copy',
    'data-lang',
    'data-source',
    'data-tex',
    'aria-label',
    'role',
  ],
}

function chatMarkdownImageAttrHook(node: Element, event: UponSanitizeAttributeHookEvent) {
  if (node.tagName !== 'IMG' || event.attrName !== 'src') return
  const value = event.attrValue.trim()
  // DOMPurify's data-URI image exception bypasses ALLOWED_URI_REGEXP.
  if (/^data:/i.test(value) && !/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$/i.test(value)) {
    event.keepAttr = false
  }
}

const SALES_CONTRACT_SANITIZE_CONFIG: Config = {
  ...CHAT_BUBBLE_CONFIG,
  ALLOWED_TAGS: [...(CHAT_BUBBLE_CONFIG.ALLOWED_TAGS as string[]), 'input', 'button'],
  ALLOWED_ATTR: [
    ...(CHAT_BUBBLE_CONFIG.ALLOWED_ATTR as string[]),
    'type',
    'value',
    'min',
    'max',
    'step',
    'disabled',
    'aria-hidden',
    'role',
    'data-row-id',
    'data-field',
    'data-index',
    'data-task-id',
  ],
}

export function sanitizeChatBubbleHtml(raw: string | undefined | null): string {
  const dirty = String(raw ?? '')
  if (!dirty) return ''
  return DOMPurify.sanitize(dirty, CHAT_BUBBLE_CONFIG)
}

/** 助手回复：按 Markdown 渲染后再消毒（表格、列表、粗体等）。 */
export function sanitizeChatBubbleMarkdown(raw: string | undefined | null): string {
  const stripped = stripInternalMarkers(String(raw ?? ''))
  if (!stripped) return ''
  const html = renderMarkdown(stripped)
  DOMPurify.addHook('uponSanitizeAttribute', chatMarkdownImageAttrHook)
  try {
    return DOMPurify.sanitize(html, CHAT_MARKDOWN_CONFIG)
  } finally {
    DOMPurify.removeHook('uponSanitizeAttribute', chatMarkdownImageAttrHook)
  }
}

function sanitizedHtmlToPlainText(sanitizedHtml: string): string {
  if (!sanitizedHtml) return ''
  if (typeof DOMParser === 'undefined') {
    return DOMPurify.sanitize(sanitizedHtml, { ALLOWED_TAGS: [], ALLOWED_ATTR: [], KEEP_CONTENT: true })
  }
  const doc = new DOMParser().parseFromString(sanitizedHtml, 'text/html')
  doc.body.querySelectorAll('br').forEach((node) => node.replaceWith(doc.createTextNode('\n')))
  return String(doc.body.textContent || '').replace(/\u00a0/g, ' ')
}

/** 将不可信 HTML 转成纯文本；先由 DOMPurify 消毒，再由 DOM 解析器提取 textContent。 */
export function plainTextFromChatHtml(raw: string | undefined | null): string {
  return sanitizedHtmlToPlainText(sanitizeChatBubbleHtml(raw))
}

/** Recover message storage without ever feeding decoded literal code back into the HTML parser. */
export function chatMarkdownFromContent(raw: string | undefined | null): string {
  const text = mapOutsideChatCode(String(raw ?? ''), prose => {
    if (CHAT_HTML_FRAGMENT.test(prose)) return plainTextFromChatHtml(prose)
    if (!prose.includes('&')) return prose
    return DOMPurify.sanitize(prose.replaceAll('<', '&lt;'), {
      ALLOWED_TAGS: [], ALLOWED_ATTR: [], RETURN_DOM_FRAGMENT: true,
    }).textContent ?? ''
  })
  // Older clients escaped already-encoded quotation marks. Only normalize the
  // legacy quote entities in prose so code can display and copy literal entities.
  return mapOutsideChatCode(text, prose => prose
    .replace(/&(?:quot|#34|#x22);/gi, '"').replace(/&(?:apos|#39|#x27);/gi, "'"))
}

/** 将不可信 Markdown 转成纯文本，供预览、TTS 与请求上下文使用。 */
export function plainTextFromChatMarkdown(raw: string | undefined | null): string {
  return sanitizedHtmlToPlainText(sanitizeChatBubbleMarkdown(raw))
}

export type TaskSummarySanitizeInput = {
  type?: string
  summary?: string
}

export function sanitizeTaskSummaryHtml(task: TaskSummarySanitizeInput): string {
  const dirty = String(task.summary ?? '')
  if (!dirty) return ''
  const t = String(task.type || '')
  if (t === 'sales_contract' && dirty.includes('sales-contract-excel-preview')) {
    return DOMPurify.sanitize(dirty, SALES_CONTRACT_SANITIZE_CONFIG)
  }
  return DOMPurify.sanitize(dirty, CHAT_BUBBLE_CONFIG)
}

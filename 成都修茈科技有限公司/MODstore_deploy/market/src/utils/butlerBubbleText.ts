/**
 * 官网/工作台小C 气泡文案：转义 + 轻量 markdown + 可点击链接。
 * 仅允许 http(s) 与站内绝对路径，禁止 javascript: 等危险协议。
 */

const SAFE_ABS = /^https?:\/\//i
const SAFE_REL = /^\/[A-Za-z0-9][A-Za-z0-9_\-./%?#=&]*$/

function escapeHtml(src: string): string {
  return String(src || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function isSafeHref(href: string): boolean {
  const h = String(href || '').trim()
  if (!h) return false
  if (SAFE_ABS.test(h)) return !/^https?:\/\/\s*$/i.test(h)
  return SAFE_REL.test(h)
}

function anchor(href: string, label: string): string {
  const abs = SAFE_ABS.test(href)
  const extra = abs ? ' target="_blank" rel="noopener noreferrer"' : ''
  return `<a class="bubble-link" href="${escapeHtml(href)}"${extra}>${label}</a>`
}

/** Render links in one pass; generated anchors must never be re-linkified. */
function renderInline(content: string): string {
  const escaped = escapeHtml(content).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  const link = /\[([^\]\n]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s<&]+)|(^|[\s：:（(>【\d.]|[^\w/"';])(\/[A-Za-z0-9][A-Za-z0-9_\-./%?#=&]{0,160})(?=$|[\s，。；;）)\]】\n])/gm
  return escaped.replace(link, (full, label: string | undefined, rawHref: string | undefined, bare: string | undefined, prefix: string | undefined, path: string | undefined) => {
    if (rawHref !== undefined) {
      const href = rawHref.replace(/&amp;/g, '&')
      return isSafeHref(href) ? anchor(href, label || '') : (label || '')
    }
    if (bare !== undefined) {
      const url = bare.replace(/[.,;!?）]+$/, '')
      return isSafeHref(url.replace(/&amp;/g, '&')) ? anchor(url.replace(/&amp;/g, '&'), url) + bare.slice(url.length) : full
    }
    if (path !== undefined && isSafeHref(path.replace(/&amp;/g, '&'))) {
      return (prefix || '') + anchor(path.replace(/&amp;/g, '&'), path)
    }
    return full
  }).replace(/\n/g, '<br>')
}

/** Escaped compact Markdown; fenced code never executes or linkifies URLs. */
export function renderButlerBubbleHtml(content: string): string {
  const fenced = /(```[^\n`]*\r?\n[\s\S]*?```)/g
  return String(content || '').split(fenced).map((part) => {
    const code = /^```[^\n`]*\r?\n([\s\S]*?)```$/.exec(part)
    if (code) return '<pre class="bubble-code"><code>' + escapeHtml(code[1]) + '</code></pre>'
    return renderInline(part)
  }).join('')
}

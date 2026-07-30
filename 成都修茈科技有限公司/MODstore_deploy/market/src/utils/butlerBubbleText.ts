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
  return `<a class="bubble-link" href="${href}"${extra}>${label}</a>`
}

/** 将已转义文本中的 markdown 链接、裸 URL、站内路径变成 <a> */
export function renderButlerBubbleHtml(content: string): string {
  let html = escapeHtml(content)

  // [文案](url) —— url 已转义，还原常见实体后校验
  html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, label: string, rawHref: string) => {
    const href = rawHref
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
    if (!isSafeHref(href)) return label
    return anchor(href, label)
  })

  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

  // 裸 https?://
  html = html.replace(/(https?:\/\/[^\s<&]+)/gi, (url) => {
    if (!isSafeHref(url)) return url
    return anchor(url, url)
  })

  // 站内路径：/market/ /contact.html …
  // 跳过已在 href="..." 内的匹配
  html = html.replace(
    /(^|[\s：:（(>【\d.]|[^\w/"'])(\/[A-Za-z0-9][A-Za-z0-9_\-./%?#=&]{0,160})(?=$|[\s，。；;）)\]】\n])/gm,
    (full, pre: string, path: string) => {
      if (/href=["']$/.test(pre) || pre.endsWith('="') || pre.endsWith("='")) return full
      if (!isSafeHref(path)) return full
      return `${pre}${anchor(path, path)}`
    },
  )

  return html.replace(/\n/g, '<br>')
}

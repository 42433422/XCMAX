/** 收集当前页面可见信息，用于给 LLM 提供上下文 */
export function serializeVisibleDom(): string {
  const parts: string[] = []

  // 页面标题
  const title = document.title || ''
  if (title) parts.push(`页面标题：${title}`)

  // 当前路由
  parts.push(`当前路径：${window.location.pathname}`)

  // H1-H3
  const headings = Array.from(document.querySelectorAll('h1, h2, h3'))
    .map((el) => el.textContent?.trim())
    .filter(Boolean)
    .slice(0, 8)
  if (headings.length) parts.push(`页面标题区：${headings.join(' | ')}`)

  // 可见按钮
  const buttons = Array.from(document.querySelectorAll('button, [role="button"], a.btn, .btn'))
    .filter((el) => isVisible(el))
    .map((el) => el.textContent?.trim() || (el as HTMLElement).getAttribute('aria-label') || '')
    .filter(Boolean)
    .slice(0, 20)
  if (buttons.length) parts.push(`页面按钮：${buttons.join(' | ')}`)

  // input placeholder
  const inputs = Array.from(document.querySelectorAll('input[placeholder], textarea[placeholder]'))
    .filter((el) => isVisible(el))
    .map((el) => (el as HTMLInputElement).placeholder)
    .filter(Boolean)
    .slice(0, 10)
  if (inputs.length) parts.push(`输入框提示：${inputs.join(' | ')}`)

  // 表格表头
  const ths = Array.from(document.querySelectorAll('th'))
    .map((el) => el.textContent?.trim())
    .filter(Boolean)
    .slice(0, 15)
  if (ths.length) parts.push(`表格列：${ths.join(' | ')}`)

  // 主要文本（限 400 字）
  const main =
    document.querySelector('main')?.textContent?.replace(/\s+/g, ' ').trim().slice(0, 400) || ''
  if (main) parts.push(`页面主要内容：${main}`)

  return parts.join('\n')
}

function isVisible(el: Element): boolean {
  if (!(el instanceof HTMLElement)) return true
  const style = window.getComputedStyle(el)
  return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0'
}

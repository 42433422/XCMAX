/**
 * AI 客服气泡：转义 HTML，并把「提交工单」等动作词变成可点击链接。
 */

function escapeHtml(src: string): string {
  return String(src || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** data-cs-action 取值：submit-ticket */
export function renderCsBubbleHtml(content: string): string {
  let html = escapeHtml(content)
  // 「提交工单」或裸 提交工单（避免已在标签内重复替换）
  html = html.replace(/「提交工单」|提交工单/g, (m) => {
    const label = m.includes('「') ? '提交工单' : m
    const wrapped = m.includes('「') ? `「${label}」` : label
    return `<a class="cs-action-link" href="#" role="button" data-cs-action="submit-ticket">${wrapped}</a>`
  })
  return html.replace(/\n/g, '<br>')
}

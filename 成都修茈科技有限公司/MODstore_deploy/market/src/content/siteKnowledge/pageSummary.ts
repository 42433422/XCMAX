/** 跨域页面摘要汇总：官网 + 市场统一结构化摘要（原 siteKnowledge 单体拆分） */
import { getCorpPageKnowledge } from './corpPages'
import { getMarketPageKnowledge } from './marketRoutes'

export function getStructuredPageSummary(opts: { corpPathname?: string; routeName?: string | null; domExcerpt?: string }): string {
  const corp = opts.corpPathname != null ? getCorpPageKnowledge(undefined, opts.corpPathname) : null
  const market = opts.routeName ? getMarketPageKnowledge(opts.routeName) : null
  const page = market || corp
  if (!page) return opts.domExcerpt?.slice(0, 800) || ''
  const bullets = page.highlights.map((h) => `• ${h}`).join('\n')
  let text = `${page.summary}\n\n要点：\n${bullets}`
  if (opts.domExcerpt?.trim()) {
    text += `\n\n页面可见内容（节选）：\n${opts.domExcerpt.slice(0, 400)}`
  }
  return text.slice(0, 1200)
}

import { describe, expect, it } from 'vitest'
import { renderButlerBubbleHtml } from './butlerBubbleText'

describe('renderButlerBubbleHtml', () => {
  it('linkifies markdown links with 点我跳转 label', () => {
    const html = renderButlerBubbleHtml('请 [点我打开 AI 市场](/market/) 继续')
    expect(html).toContain('href="/market/"')
    expect(html).toContain('点我打开 AI 市场')
    expect(html).not.toContain('javascript:')
  })

  it('linkifies bare site paths', () => {
    const html = renderButlerBubbleHtml('会员方案：/market/plans\n联系：/contact.html')
    expect(html).toContain('href="/market/plans"')
    expect(html).toContain('href="/contact.html"')
    expect(html).toContain('<br>')
  })

  it('linkifies absolute https urls with target blank', () => {
    const html = renderButlerBubbleHtml('官网 https://xiu-ci.com/download.html')
    expect(html).toContain('href="https://xiu-ci.com/download.html"')
    expect(html).toContain('target="_blank"')
  })

  it('rejects javascript links', () => {
    const html = renderButlerBubbleHtml('[x](javascript:alert(1))')
    expect(html).not.toContain('javascript:')
    expect(html).toContain('x')
  })

  it('escapes html before linkify', () => {
    const html = renderButlerBubbleHtml('<script>alert(1)</script> /market/')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
    expect(html).toContain('href="/market/"')
  })
})

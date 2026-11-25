import { describe, expect, it } from 'vitest'
import { renderButlerBubbleHtml } from './butlerBubbleText'
import { renderCsBubbleHtml } from './csBubbleText'

describe('renderButlerBubbleHtml', () => {
  it.each([renderButlerBubbleHtml, renderCsBubbleHtml])('renders original notes as text at the display boundary', (render) => {
    const fixture = new DOMParser().parseFromString('<img src="x">', 'text/html')
    const image = fixture.querySelector('img')
    image?.setAttribute('onerror', 'literal()')
    expect(image?.getAttribute('src')).toBe('x')
    expect(image?.getAttribute('onerror')).toBe('literal()')
    const note = `客户 A&B <script>literal()</script> ${fixture.body.innerHTML} &lt;原实体&gt;`
    const doc = new DOMParser().parseFromString(render(note), 'text/html')
    expect(doc.body.textContent).toBe(note)
    expect(doc.querySelector('script, img, [onerror]')).toBeNull()
  })

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

  it('never nests anchors when markdown and bare URLs appear together', () => {
    const html = renderButlerBubbleHtml('查看 [官网](https://xiu-ci.com/download.html) 和 https://xiu-ci.com/')
    const doc = new DOMParser().parseFromString(html, 'text/html')
    const links = doc.querySelectorAll('a')
    expect(links).toHaveLength(2)
    expect(links[0].getAttribute('href')).toBe('https://xiu-ci.com/download.html')
    expect(links[1].getAttribute('href')).toBe('https://xiu-ci.com/')
    expect(links[0].querySelector('a')).toBeNull()
  })

  it('escapes fenced code without linking or executing syntax inside it', () => {
    const html = renderButlerBubbleHtml('代码：\\n```ts\\nconst text = "<script>"; // https://xiu-ci.com\\n```')
    const doc = new DOMParser().parseFromString(html, 'text/html')
    expect(doc.querySelector('pre code')?.textContent).toContain('<script>')
    expect(doc.querySelector('a, script')).toBeNull()
  })

  it('does not double-decode entities into link attributes', () => {
    const html = renderButlerBubbleHtml(
      '[x](https://xiu-ci.com/&quot;onmouseover=&quot;alert(1))',
    )
    expect(html).not.toContain(' onmouseover=')
    expect(html).toContain('&amp;quot;onmouseover=')
  })
})

import { describe, expect, it } from 'vitest'
import { renderMarkdown, stripInternalMarkers } from './lightMarkdown'

describe('lightMarkdown.renderMarkdown', () => {
  it('renders basic paragraph and bold', () => {
    const html = renderMarkdown('hello **world**')
    expect(html).toContain('<p class="md-p">hello <strong>world</strong></p>')
  })

  it('renders headings with class names', () => {
    const html = renderMarkdown('# 一档\n\n## 二级')
    expect(html).toContain('<h1 class="md-h md-h1">一档</h1>')
    expect(html).toContain('<h2 class="md-h md-h2">二级</h2>')
  })

  it('renders unordered list', () => {
    const html = renderMarkdown('- 苹果\n- 香蕉\n- 西瓜')
    expect(html).toContain('<ul class="md-list">')
    expect(html.match(/<li class="md-li">/g)?.length).toBe(3)
    expect(html).toContain('苹果')
  })

  it('renders ordered list', () => {
    const html = renderMarkdown('1. 一\n2. 二\n3. 三')
    expect(html).toContain('<ol class="md-list">')
    expect(html.match(/<li class="md-li">/g)?.length).toBe(3)
  })

  it('renders fenced code block with language label', () => {
    const html = renderMarkdown('```python\nprint("hi")\n```')
    expect(html).toContain('class="md-code"')
    expect(html).toContain('data-lang="python"')
    expect(html).toContain('print(&quot;hi&quot;)')
  })

  it('renders mermaid as placeholder for async render', () => {
    const html = renderMarkdown('```mermaid\ngraph TD;A-->B\n```')
    expect(html).toContain('class="md-mermaid"')
    expect(html).toContain('data-source="graph TD;A--&gt;B"')
  })

  it('renders inline code', () => {
    const html = renderMarkdown('use `npm run build` to compile')
    expect(html).toContain('<code class="md-code-inline">npm run build</code>')
  })

  it('renders tables', () => {
    const html = renderMarkdown('| 字段 | 类型 |\n| --- | --- |\n| name | string |\n| age | number |')
    expect(html).toContain('class="md-table"')
    expect(html).toContain('<th>字段</th>')
    expect(html).toContain('<td>name</td>')
  })

  it('escapes raw HTML to prevent XSS', () => {
    const html = renderMarkdown('hello <script>alert(1)</script>')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })

  it('rejects javascript: URL in links', () => {
    const html = renderMarkdown('[click](javascript:alert(1))')
    expect(html).not.toContain('href="javascript:')
    expect(html).toContain('click')
  })

  it('rejects sandbox: pseudo-download URLs in links', () => {
    const html = renderMarkdown('[下载：合同.docx](sandbox:/mnt/data/contract.docx)')
    expect(html).not.toContain('href="sandbox:')
    expect(html).toContain('下载：合同.docx')
  })

  it('renders block math placeholder', () => {
    const html = renderMarkdown('$$E = mc^2$$')
    expect(html).toContain('md-math-block')
    expect(html).toContain('data-tex="E = mc^2"')
  })

  it('renders inline math placeholder', () => {
    const html = renderMarkdown('能量公式 \\(E=mc^2\\) 很有名')
    expect(html).toContain('md-math-inline')
    expect(html).toContain('data-tex="E=mc^2"')
  })

  it('renders blockquote', () => {
    const html = renderMarkdown('> 引用一句\n> 第二行')
    expect(html).toContain('<blockquote class="md-quote">')
    expect(html).toContain('引用一句')
  })
})

describe('lightMarkdown.stripInternalMarkers', () => {
  it('removes plan-protocol markers', () => {
    const out = stripInternalMarkers('正文\n<<<PLAN_DETAILS>>>some<<<END_PLAN_DETAILS>>>\n尾巴')
    expect(out).not.toContain('PLAN_DETAILS')
    expect(out).toContain('正文')
    expect(out).toContain('尾巴')
  })

  it('removes truncated protocol opener without closing tag', () => {
    const out = stripInternalMarkers('摘要<<<PLAN_OPTIONS>>')
    expect(out).toBe('摘要')
    expect(out).not.toContain('PLAN_OPTIONS')
  })
})

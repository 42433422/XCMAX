import { describe, it, expect } from 'vitest'
import { renderMarkdown, stripInternalMarkers } from './lightMarkdown'

describe('lightMarkdown deep branches', () => {
  it('renders headings of all levels', () => {
    expect(renderMarkdown('# H1')).toContain('<h1')
    expect(renderMarkdown('###### H6')).toContain('<h6')
  })

  it('renders unordered and ordered lists', () => {
    const ul = renderMarkdown('- a\n- b')
    expect(ul).toContain('<ul')
    expect(ul).toContain('<li')
    const ol = renderMarkdown('1. one\n2. two')
    expect(ol).toContain('<ol')
  })

  it('renders blockquote', () => {
    expect(renderMarkdown('> quoted line')).toContain('<blockquote')
  })

  it('renders horizontal rule', () => {
    expect(renderMarkdown('---')).toContain('<hr')
  })

  it('renders GFM table with alignment', () => {
    const md = '| A | B |\n| :--- | :---: |\n| 1 | 2 |'
    const html = renderMarkdown(md)
    expect(html).toContain('<table')
    expect(html).toContain('text-align:left')
    expect(html).toContain('text-align:center')
  })

  it('renders right-aligned table column', () => {
    const md = 'col\n\n| A | B |\n| --- | ---: |\n| 1 | 2 |'
    const html = renderMarkdown(md)
    expect(html).toContain('text-align:right')
  })

  it('renders fenced code block with language', () => {
    const html = renderMarkdown('```js\nconst x = 1\n```')
    expect(html).toContain('md-code__body')
    expect(html).toContain('data-lang="js"')
  })

  it('renders mermaid placeholder', () => {
    const html = renderMarkdown('```mermaid\ngraph TD\nA-->B\n```')
    expect(html).toContain('md-mermaid')
  })

  it('renders block and inline math', () => {
    expect(renderMarkdown('\\[ x^2 \\]')).toContain('md-math-block')
    expect(renderMarkdown('inline \\( a+b \\) here')).toContain('md-math-inline')
    expect(renderMarkdown('$$ y=mx $$')).toContain('md-math-block')
  })

  it('renders images with safe url and drops javascript urls', () => {
    expect(renderMarkdown('![alt](https://x.com/i.png)')).toContain('<img')
    expect(renderMarkdown('![alt](javascript:alert(1))')).not.toContain('<img')
  })

  it('renders autolinks', () => {
    expect(renderMarkdown('visit https://example.com now')).toContain('md-link')
  })

  it('renders emphasis variants', () => {
    expect(renderMarkdown('__bold__')).toContain('<strong>')
    expect(renderMarkdown('*italic*')).toContain('<em>')
    expect(renderMarkdown('_em_')).toContain('<em>')
    expect(renderMarkdown('~~del~~')).toContain('<del>')
  })

  it('handles empty input', () => {
    expect(renderMarkdown('')).toBe('')
    expect(renderMarkdown(null as unknown as string)).toBe('')
  })

  it('stripInternalMarkers removes all marker blocks', () => {
    const src = 'a<<<PLAN_OPTIONS>>>x<<<END_PLAN_OPTIONS>>>b<<<CHECKLIST>>>y<<<END>>>c'
    expect(stripInternalMarkers(src)).toBe('abc')
    expect(stripInternalMarkers('')).toBe('')
  })
})

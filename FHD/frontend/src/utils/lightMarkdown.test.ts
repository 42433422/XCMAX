import { describe, expect, it } from 'vitest'
import { normalizeModelLineBreaks, renderMarkdown, stripInternalMarkers } from './lightMarkdown'

describe('lightMarkdown', () => {
  it('escapes raw html and renders bold', () => {
    const html = renderMarkdown('**hi** <script>alert(1)</script>')
    expect(html).toContain('<strong>hi</strong>')
    expect(html).not.toContain('<script>')
  })

  it('renders inline code and links safely', () => {
    const html = renderMarkdown('see [`code`](https://example.com) and `x`')
    expect(html).toContain('href="https://example.com"')
    expect(html).toContain('<code')
    expect(html).toContain('target="_blank"')
    expect(renderMarkdown('[inventory.xlsx](/api/agent/runs/run_test/artifacts/xlsx_test)')).toContain('target="_self"')
    expect(renderMarkdown('[file](//evil.example/api/agent/runs/run_test/artifacts/xlsx_test)')).not.toContain('target="_self"')
  })

  it.each([
    '```text\nsafe code\n```\n',
    '\u0000MD_PLACEHOLDER_0\u0001',
    '\u0000MD_PLACEHOLDER_forged',
  ])('escapes raw HTML after a fence or forged placeholder: %j', (prefix) => {
    const marker = '<aside id="markdown-injection-probe">raw node</aside>'
    const body = new DOMParser().parseFromString(renderMarkdown(prefix + marker), 'text/html').body
    expect(body.querySelector('#markdown-injection-probe')).toBeNull()
    expect(body.textContent).toContain(marker)
  })

  it('keeps fences as separate blocks next to prose and other fences', () => {
    const body = new DOMParser().parseFromString(renderMarkdown([
      'before', '```text', 'first <code>', '```',
      '```js', 'second()', '```', 'after **bold**',
    ].join('\n')), 'text/html').body
    expect([...body.children].map(node => node.tagName)).toEqual(['P', 'PRE', 'PRE', 'P'])
    expect([...body.querySelectorAll('.md-code__body')].map(node => node.textContent))
      .toEqual(['first <code>', 'second()'])
    expect(body.lastElementChild?.textContent).toBe('after bold')
    expect(body.querySelectorAll('.md-code__copy')).toHaveLength(2)
  })

  it('preserves Mermaid source next to escaped text', () => {
    const source = 'graph TD; A-->B'
    const body = new DOMParser().parseFromString(renderMarkdown(
      '```mermaid\n' + source + '\n```\n<aside id="markdown-injection-probe">note</aside>',
    ), 'text/html').body
    expect(body.querySelector('.md-mermaid')?.getAttribute('data-source')).toBe(source)
    expect(body.querySelector('#markdown-injection-probe')).toBeNull()
  })

  it('stripInternalMarkers removes plan blocks', () => {
    const src = 'hello <<<PLAN_DETAILS>>>secret<<<END_PLAN_DETAILS>>> world'
    expect(stripInternalMarkers(src)).toBe('hello  world')
  })

  it('normalizeModelLineBreaks converts br tags to newlines', () => {
    expect(normalizeModelLineBreaks('a<br>b<br/>c')).toBe('a\nb\nc')
  })
})

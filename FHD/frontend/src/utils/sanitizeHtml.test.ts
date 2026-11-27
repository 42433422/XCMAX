import { describe, expect, it, vi } from 'vitest'
import DOMPurify from 'dompurify'
import { chatMarkdownFromContent, plainTextFromChatHtml, sanitizeChatBubbleHtml, sanitizeChatBubbleMarkdown, sanitizeTaskSummaryHtml } from './sanitizeHtml'

describe('chatMarkdownFromContent', () => {
  it('decodes named and numeric entities while preserving literal text', () => {
    expect(chatMarkdownFromContent('C++ <vector> &amp; &copy; &nbsp;&#x1f680; &#128; &unknown;'))
      .toBe('C++ <vector> & © \u00a0🚀 € &unknown;')
  })

  const imageFixture = new DOMParser().parseFromString('<img src=x> &amp; literal', 'text/html')
  imageFixture.querySelector('img')?.setAttribute('onerror', 'alert(1)')

  it.each([
    '&lt;script&gt;alert(1)&lt;/script&gt;',
    '&lt;/textarea&gt;&lt;img src=x onerror=alert(1)&gt;',
    '&#60;svg onload=alert(1)&#62;',
    imageFixture.body.innerHTML,
  ])('keeps decoded markup as literal text through Markdown rendering: %s', (raw) => {
    expect(raw).toContain('alert(1)')
    const markdown = chatMarkdownFromContent(raw)
    const body = new DOMParser().parseFromString(sanitizeChatBubbleMarkdown(markdown), 'text/html').body
    expect(body.querySelector('script, img, svg, textarea')).toBeNull()
    expect(body.textContent?.trim()).toBe(markdown)
  })

  it('decodes storage escaping once except for legacy double-escaped quotes', () => {
    expect(chatMarkdownFromContent('&amp;lt;tag&amp;gt; &amp;quot;正常&amp;quot;'))
      .toBe('&lt;tag&gt; "正常"')
  })

  it.each(['\n```', ''])('preserves entity spelling in complete and streaming code fences', (closing) => {
    const code = '```html\n&lt;img&gt; &amp;quot; <tag>' + closing
    expect(chatMarkdownFromContent('before &amp;\n' + code)).toBe('before &\n' + code)
  })
})

describe('plainTextFromChatHtml', () => {
  it.each(['<script', '<script>alert(1)</script>', '<br><br />&nbsp;'])('treats non-visible shell content %s as empty', (html) => {
    expect(plainTextFromChatHtml(html).trim()).toBe('')
  })

  it('preserves visible reply text around unsafe or unfinished tags', () => {
    expect(plainTextFromChatHtml('<p>已有回复<br>下一行</p><script>alert(1)</script><script').trim()).toBe('已有回复\n下一行')
  })
})

describe('sanitizeChatBubbleHtml', () => {
  it('returns empty string for null/empty', () => {
    expect(sanitizeChatBubbleHtml(null)).toBe('')
    expect(sanitizeChatBubbleHtml('')).toBe('')
  })

  it('strips script tags', () => {
    const out = sanitizeChatBubbleHtml('<p>hi</p><script>alert(1)</script>')
    expect(out).toContain('<p>hi</p>')
    expect(out).not.toContain('<script>')
  })

  it('removes inline event handlers', () => {
    const out = sanitizeChatBubbleHtml('<a href="#" onclick="evil()">x</a>')
    expect(out).not.toContain('onclick')
  })

  it('keeps allowed formatting tags', () => {
    const out = sanitizeChatBubbleHtml('<strong>bold</strong> <em>i</em>')
    expect(out).toContain('<strong>bold</strong>')
    expect(out).toContain('<em>i</em>')
  })
})

describe('sanitizeChatBubbleMarkdown', () => {
  it('keeps shared sanitizer hooks and does not allow image data URLs as links', () => {
    const existingHook = vi.fn()
    DOMPurify.addHook('uponSanitizeAttribute', existingHook)
    try {
      const output = sanitizeChatBubbleMarkdown('[image](data:image/png;base64,AA==)')
      expect(output).not.toContain('href=')
      existingHook.mockClear()
      sanitizeChatBubbleHtml('<p title="kept">text</p>')
      expect(existingHook).toHaveBeenCalled()
    } finally {
      DOMPurify.removeHook('uponSanitizeAttribute', existingHook)
    }
  })

  it('renders markdown bold into strong', () => {
    const out = sanitizeChatBubbleMarkdown('**bold**')
    expect(out).toContain('<strong>bold</strong>')
  })

  it('returns empty for blank input', () => {
    expect(sanitizeChatBubbleMarkdown('')).toBe('')
    expect(sanitizeChatBubbleMarkdown(null)).toBe('')
  })

  it('converts model literal br tags into line breaks', () => {
    const out = sanitizeChatBubbleMarkdown('第一行<br><br>- 列表项')
    expect(out).not.toContain('&lt;br')
    expect(out).not.toContain('<br>')
    expect(out).toContain('列表项')
    expect(out).toMatch(/<li[^>]*>/)
  })

  it('preserves original prompt characters inside a rendered code block', () => {
    const code = "if x < 3 and y > 0:\n    print('A&B')"
    const out = sanitizeChatBubbleMarkdown('```python\n' + code + '\n```')
    const rendered = new DOMParser().parseFromString(out, 'text/html')
    expect(rendered.querySelector('code')?.textContent?.trim()).toBe(code)
  })
})

describe('sanitizeTaskSummaryHtml', () => {
  it('returns empty when no summary', () => {
    expect(sanitizeTaskSummaryHtml({})).toBe('')
    expect(sanitizeTaskSummaryHtml({ summary: '' })).toBe('')
  })

  it('sanitizes generic summary', () => {
    const out = sanitizeTaskSummaryHtml({
      type: 'generic',
      summary: '<p>ok</p><script>x</script>',
    })
    expect(out).toContain('<p>ok</p>')
    expect(out).not.toContain('<script>')
  })

  it('keeps preview controls and data while removing inline handlers', () => {
    const fixture = new DOMParser().parseFromString(
      `<div class="sales-contract-excel-preview">
        <input class="sales-contract-excel-preview__qty-input" type="number" data-row-id="1" value="10" />
        <button class="sales-contract-row-action-btn" data-row-id="1">Edit</button>
      </div>`,
      'text/html',
    )
    const input = fixture.querySelector('input')
    const button = fixture.querySelector('button')
    input?.setAttribute('onchange', 'f()')
    button?.setAttribute('onclick', 'f()')
    expect(input?.getAttribute('onchange')).toBe('f()')
    expect(button?.getAttribute('onclick')).toBe('f()')
    const out = sanitizeTaskSummaryHtml({ type: 'sales_contract', summary: fixture.body.innerHTML })
    expect(out).toContain('input')
    expect(out).toContain('button')
    expect(out).toContain('data-row-id="1"')
    expect(out).toContain('value="10"')
    expect(out).not.toContain('onchange')
    expect(out).not.toContain('onclick')
  })

  it('strips handlers when type is not sales_contract', () => {
    const html =
      '<div class="sales-contract-excel-preview">' + '<input class="sales-contract-excel-preview__qty-input" onchange="f()" /></div>'
    const out = sanitizeTaskSummaryHtml({ type: 'other', summary: html })
    expect(out).not.toContain('onchange')
  })
})

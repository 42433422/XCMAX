import { describe, expect, it } from 'vitest'
import { renderCsBubbleHtml } from './csBubbleText'

describe('renderCsBubbleHtml', () => {
  it('linkifies 提交工单 and escapes html', () => {
    const html = renderCsBubbleHtml('直接回「提交工单」即可。<script>x</script>')
    expect(html).toContain('data-cs-action="submit-ticket"')
    expect(html).toContain('提交工单')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })
})

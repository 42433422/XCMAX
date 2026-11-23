import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import MessageBody from './MessageBody.vue'

enableAutoUnmount(afterEach)

describe('MessageBody with the real Markdown renderer', () => {
  it('displays original JSON code and notes without creating HTML elements', () => {
    const code = 'if a < b:\n    print("<script>literal()</script> &lt;entity&gt; A&B")'
    const fixture = new DOMParser().parseFromString('<img src=x>', 'text/html')
    fixture.querySelector('img')?.setAttribute('onerror', 'literal()')
    const note = `客户备注 ${fixture.body.innerHTML} &lt;原实体&gt; A&B`
    expect(note).toContain('onerror="literal()"')
    const content = `\`\`\`text\n${code}\n\`\`\`\n\n${note}`
    const wrapper = mount(MessageBody, { props: { content } })
    expect(wrapper.get('.md-code__body').element.textContent).toBe(code)
    expect(wrapper.text()).toContain(note)
    expect(wrapper.find('script, img, [onerror]').exists()).toBe(false)
    expect(wrapper.props('content')).toBe(content)
  })

  it.each(['png', 'jpeg', 'webp'])('renders generated %s bitmap receipts during and after streaming', async (format) => {
    const src = `data:image/${format};base64,AA==`
    const wrapper = mount(MessageBody, { props: { content: `![生成图片](${src})\n\nimage-model`, streaming: true } })
    expect(wrapper.get('img').attributes('src')).toBe(src)
    expect(wrapper.text()).toContain('image-model')
    await wrapper.setProps({ streaming: false })
    expect(wrapper.get('img').attributes('src')).toBe(src)
  })

  it.each([
    'data:image/svg+xml;base64,PHN2Zy8+',
    'data:image/gif;base64,R0lGODlh',
    'data:image/bmp;base64,Qk0=',
    'data:image/png,raw-data',
    'data:image/png;base64,',
    'data:image/png;base64,AA==;extra',
    'data:text/html;base64,PHNjcmlwdD4=',
    'javascript:alert(1)',
  ])('rejects unsafe or unsupported generated image URLs: %s', (src) => {
    const wrapper = mount(MessageBody, { props: { content: `![生成图片](${src})` } })
    expect(wrapper.find('img[src]').exists()).toBe(false)
  })

  it.each([false, true])('keeps raw HTML after a code fence as text (streaming=%s)', (streaming) => {
    const marker = '<aside id="markdown-injection-probe">raw node</aside>'
    const wrapper = mount(MessageBody, { props: {
      content: '```text\nsafe code\n```\n' + marker, streaming,
    } })
    expect(wrapper.find('#markdown-injection-probe').exists()).toBe(false)
    expect(wrapper.text()).toContain(marker)
    expect(wrapper.find('.md-code__body').text()).toBe('safe code')
    expect(wrapper.find('.msg-body__cursor').exists()).toBe(streaming)
  })

  it('uses the existing sanitizer URL policy before inserting Markdown links', () => {
    const wrapper = mount(MessageBody, { props: {
      content: '[local report](file:///tmp/xcmax-markdown-probe)',
    } })
    expect(wrapper.find('a').text()).toBe('local report')
    expect(wrapper.find('a').attributes('href')).toBeUndefined()
  })

  it('retains code-copy, math, table and same-origin artifact markup', () => {
    const wrapper = mount(MessageBody, { props: { content: [
      '```text', 'safe <code>', '```', '', '\\(a+b\\)', '',
      '| Name | Count |', '| --- | --- |', '| Value | 1 |', '',
      '[report](/api/agent/runs/run_test/artifacts/xlsx_test)',
    ].join('\n') } })
    expect(wrapper.find('.md-code__body').text()).toBe('safe <code>')
    expect(wrapper.find('.md-code__copy').attributes('data-copy')).toBe('1')
    expect(wrapper.find('.md-code__body').attributes('data-lang')).toBe('text')
    expect(wrapper.find('.md-math').attributes('data-tex')).toBe('a+b')
    expect(wrapper.find('table td').text()).toBe('Value')
    expect(wrapper.find('a').attributes('href')).toBe('/api/agent/runs/run_test/artifacts/xlsx_test')
    expect(wrapper.find('a').attributes('target')).toBe('_self')
  })
})

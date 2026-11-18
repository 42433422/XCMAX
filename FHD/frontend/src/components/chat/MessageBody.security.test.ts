import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import MessageBody from './MessageBody.vue'

enableAutoUnmount(afterEach)

describe('MessageBody with the real Markdown renderer', () => {
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

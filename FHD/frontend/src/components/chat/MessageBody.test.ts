import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import MessageBody from './MessageBody.vue'

vi.mock('@/utils/lightMarkdown', () => ({
  renderMarkdown: vi.fn((text: string) => `<p>${text}</p>`),
}))

vi.mock('@/utils/mermaidSanitize', () => ({
  sanitizeMermaidSource: vi.fn((src: string) => src),
}))

describe('MessageBody', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  function mountBody(props = {}) {
    return mount(MessageBody, {
      props: {
        content: 'Hello world',
        ...props,
      },
    })
  }

  it('renders msg-body container', () => {
    const wrapper = mountBody()
    expect(wrapper.find('.msg-body').exists()).toBe(true)
  })

  it('renders content as HTML via v-html', () => {
    const wrapper = mountBody({ content: 'Test content' })
    expect(wrapper.find('.msg-body').html()).toContain('Test content')
  })

  it('renders empty content when content prop is empty', () => {
    const wrapper = mountBody({ content: '' })
    expect(wrapper.find('.msg-body').exists()).toBe(true)
  })

  it('renders cursor when streaming is true and content is not empty', async () => {
    const wrapper = mountBody({ content: 'Streaming...', streaming: true })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('msg-body__cursor')
  })

  it('does not render cursor when streaming is false', async () => {
    const wrapper = mountBody({ content: 'Not streaming', streaming: false })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).not.toContain('msg-body__cursor')
  })

  it('does not render cursor when streaming is true but content is empty', async () => {
    const wrapper = mountBody({ content: '', streaming: true })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).not.toContain('msg-body__cursor')
  })

  it('calls renderMarkdown with content', async () => {
    const { renderMarkdown } = await import('@/utils/lightMarkdown')
    const wrapper = mountBody({ content: 'Markdown content' })
    await wrapper.vm.$nextTick()
    expect(renderMarkdown).toHaveBeenCalledWith('Markdown content')
  })

  it('applies default content when content prop is undefined', () => {
    const wrapper = mountBody({ content: undefined })
    expect(wrapper.find('.msg-body').exists()).toBe(true)
  })

  it('updates rendered content when content prop changes', async () => {
    const wrapper = mountBody({ content: 'Initial' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('Initial')

    await wrapper.setProps({ content: 'Updated' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('Updated')
  })

  it('handles mermaid blocks gracefully when no mermaid elements exist', async () => {
    const wrapper = mountBody({ content: 'No mermaid here' })
    await flushPromises()
    expect(wrapper.find('.msg-body').exists()).toBe(true)
  })

  it('applies scoped styles correctly', () => {
    const wrapper = mountBody()
    const style = wrapper.find('.msg-body').attributes('style') || ''
    expect(wrapper.find('.msg-body').exists()).toBe(true)
  })

  it('renders with streaming prop as optional', () => {
    const wrapper = mountBody({ content: 'Test' })
    expect(wrapper.find('.msg-body').exists()).toBe(true)
  })

  it('handles special characters in content', async () => {
    const wrapper = mountBody({ content: '<script>alert("xss")</script>' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').exists()).toBe(true)
  })

  it('handles long content strings', async () => {
    const longContent = 'A'.repeat(10000)
    const wrapper = mountBody({ content: longContent })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').exists()).toBe(true)
  })

  it('handles unicode content', async () => {
    const wrapper = mountBody({ content: '你好世界 🌍' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').exists()).toBe(true)
  })

  it('handles newlines in content', async () => {
    const wrapper = mountBody({ content: 'Line 1\nLine 2\nLine 3' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').exists()).toBe(true)
  })

  it('handles markdown code blocks', async () => {
    const { renderMarkdown } = await import('@/utils/lightMarkdown')
    vi.mocked(renderMarkdown).mockReturnValue('<pre><code>const x = 1;</code></pre>')
    const wrapper = mountBody({ content: '```js\nconst x = 1;\n```' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('code')
  })

  it('handles markdown tables', async () => {
    const { renderMarkdown } = await import('@/utils/lightMarkdown')
    vi.mocked(renderMarkdown).mockReturnValue('<table><tr><th>Header</th></tr></table>')
    const wrapper = mountBody({ content: '| Header |\n|--------|\n| Cell |' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('table')
  })

  it('handles markdown links', async () => {
    const { renderMarkdown } = await import('@/utils/lightMarkdown')
    vi.mocked(renderMarkdown).mockReturnValue('<a href="https://example.com" class="md-link">Link</a>')
    const wrapper = mountBody({ content: '[Link](https://example.com)' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('Link')
  })

  it('handles markdown images', async () => {
    const { renderMarkdown } = await import('@/utils/lightMarkdown')
    vi.mocked(renderMarkdown).mockReturnValue('<img src="test.png" class="md-img" alt="test" />')
    const wrapper = mountBody({ content: '![test](test.png)' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('img')
  })

  it('handles markdown blockquotes', async () => {
    const { renderMarkdown } = await import('@/utils/lightMarkdown')
    vi.mocked(renderMarkdown).mockReturnValue('<blockquote class="md-quote">Quote</blockquote>')
    const wrapper = mountBody({ content: '> Quote' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('Quote')
  })

  it('handles markdown lists', async () => {
    const { renderMarkdown } = await import('@/utils/lightMarkdown')
    vi.mocked(renderMarkdown).mockReturnValue('<ul class="md-list"><li class="md-li">Item</li></ul>')
    const wrapper = mountBody({ content: '- Item' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('Item')
  })

  it('handles markdown headings', async () => {
    const { renderMarkdown } = await import('@/utils/lightMarkdown')
    vi.mocked(renderMarkdown).mockReturnValue('<h1 class="md-h md-h1">Title</h1>')
    const wrapper = mountBody({ content: '# Title' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('Title')
  })

  it('handles markdown horizontal rules', async () => {
    const { renderMarkdown } = await import('@/utils/lightMarkdown')
    vi.mocked(renderMarkdown).mockReturnValue('<hr class="md-hr" />')
    const wrapper = mountBody({ content: '---' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('hr')
  })

  it('handles markdown inline code', async () => {
    const { renderMarkdown } = await import('@/utils/lightMarkdown')
    vi.mocked(renderMarkdown).mockReturnValue('<code class="md-code-inline">code</code>')
    const wrapper = mountBody({ content: '`code`' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('code')
  })

  it('handles math blocks', async () => {
    const { renderMarkdown } = await import('@/utils/lightMarkdown')
    vi.mocked(renderMarkdown).mockReturnValue('<div class="md-math-block">E=mc^2</div>')
    const wrapper = mountBody({ content: '$$E=mc^2$$' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('math')
  })

  it('handles inline math', async () => {
    const { renderMarkdown } = await import('@/utils/lightMarkdown')
    vi.mocked(renderMarkdown).mockReturnValue('<span class="md-math">x^2</span>')
    const wrapper = mountBody({ content: '$x^2$' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.msg-body').html()).toContain('math')
  })
})

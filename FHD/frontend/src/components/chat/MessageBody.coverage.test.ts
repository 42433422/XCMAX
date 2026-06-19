/**
 * Coverage ramp 测试：MessageBody.vue
 *
 * 目标：覆盖 MessageBody.vue 中所有分支，覆盖率 ≥ 95%
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'

// ─── 共享 mock 状态（vi.hoisted 确保 vi.mock 中可访问） ──────────
const mocks = vi.hoisted(() => ({
  renderMarkdown: vi.fn((s: string): string => ''),
  sanitizeMermaid: vi.fn((s: string): string => s),
  mermaidInitialize: vi.fn((): void => {}),
  mermaidRun: vi.fn(async (opts?: Record<string, unknown>): Promise<void> => {}),
}))

vi.mock('@/utils/lightMarkdown', () => ({
  renderMarkdown: (...a: unknown[]) => mocks.renderMarkdown(...(a as [string])),
}))
vi.mock('@/utils/mermaidSanitize', () => ({
  sanitizeMermaidSource: (...a: unknown[]) => mocks.sanitizeMermaid(...(a as [string])),
}))
vi.mock('mermaid', () => ({
  default: {
    initialize: (...a: unknown[]) => mocks.mermaidInitialize(...(a as [])),
    run: (...a: unknown[]) => mocks.mermaidRun(...(a as [Record<string, unknown> | undefined])),
  },
}))

// ─── RAF mock（可控执行，不自动触发） ───────────────────────────
let rafCallback: FrameRequestCallback | null = null
let rafIdCounter = 1

function setupRafMock() {
  rafCallback = null
  rafIdCounter = 1
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    rafCallback = cb
    return rafIdCounter++
  })
  vi.stubGlobal('cancelAnimationFrame', () => {
    rafCallback = null
  })
}

function flushRaf() {
  if (rafCallback) {
    const cb = rafCallback
    rafCallback = null
    cb(0)
  }
}

// ─── clipboard mock ────────────────────────────────────────────
let clipboardWriteText: ReturnType<typeof vi.fn>

function setupClipboardMock() {
  clipboardWriteText = vi.fn(async (text: string): Promise<void> => {})
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: clipboardWriteText },
    configurable: true,
    writable: true,
  })
}

// ─── 组件加载（每测试重置模块级状态） ───────────────────────────
let MessageBody: typeof import('./MessageBody.vue').default

beforeEach(async () => {
  vi.useRealTimers()
  vi.resetModules()
  setupRafMock()
  setupClipboardMock()
  // 清除所有 mock 调用记录（防止跨测试累积）
  mocks.renderMarkdown.mockClear()
  mocks.sanitizeMermaid.mockClear()
  mocks.mermaidInitialize.mockClear()
  mocks.mermaidRun.mockClear()
  // 重置默认实现
  mocks.renderMarkdown.mockImplementation((s: string): string => (s ? `<p>${s}</p>` : ''))
  mocks.sanitizeMermaid.mockImplementation((s: string): string => s)
  mocks.mermaidInitialize.mockImplementation(() => {})
  mocks.mermaidRun.mockImplementation(async () => {})
  const mod = await import('./MessageBody.vue')
  MessageBody = mod.default
})

// 辅助：等待所有异步操作完成
async function waitForFlush() {
  await nextTick()
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

// ─── rendered computed ─────────────────────────────────────────
describe('MessageBody rendered computed', () => {
  it('空内容返回空 HTML（无光标）', () => {
    mocks.renderMarkdown.mockImplementation(() => '')
    const wrapper = mount(MessageBody, { props: { content: '' } })
    expect(wrapper.find('.msg-body__cursor').exists()).toBe(false)
  })

  it('非 streaming 返回纯 HTML（无光标）', () => {
    mocks.renderMarkdown.mockImplementation(() => '<p>hello</p>')
    const wrapper = mount(MessageBody, { props: { content: 'hello' } })
    expect(wrapper.html()).toContain('<p>hello</p>')
    expect(wrapper.find('.msg-body__cursor').exists()).toBe(false)
  })

  it('streaming 且有内容时附加光标', () => {
    mocks.renderMarkdown.mockImplementation(() => '<p>hello</p>')
    const wrapper = mount(MessageBody, { props: { content: 'hello', streaming: true } })
    expect(wrapper.find('.msg-body__cursor').exists()).toBe(true)
  })

  it('streaming 但内容为空白时不附加光标', () => {
    mocks.renderMarkdown.mockImplementation(() => '')
    const wrapper = mount(MessageBody, { props: { content: '   ', streaming: true } })
    expect(wrapper.find('.msg-body__cursor').exists()).toBe(false)
  })

  it('streaming 且内容为空字符串时不附加光标', () => {
    mocks.renderMarkdown.mockImplementation(() => '')
    const wrapper = mount(MessageBody, { props: { content: '', streaming: true } })
    expect(wrapper.find('.msg-body__cursor').exists()).toBe(false)
  })
})

// ─── getMermaid ────────────────────────────────────────────────
describe('MessageBody getMermaid', () => {
  it('首次调用导入并初始化 mermaid', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    expect(mocks.mermaidInitialize).toHaveBeenCalledTimes(1)
  })

  it('后续调用复用已初始化的 mermaid（不再 initialize）', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    const wrapper = mount(MessageBody, { props: { content: '   ', streaming: true } })
    await waitForFlush()
    mocks.mermaidInitialize.mockClear()
    // streaming 变 false 触发再次 flush（内容空白，v-html 不重渲染）
    await wrapper.setProps({ streaming: false })
    await waitForFlush()
    expect(mocks.mermaidInitialize).not.toHaveBeenCalled()
  })
})

// ─── flushMermaid ──────────────────────────────────────────────
describe('MessageBody flushMermaid', () => {
  it('无 mermaid 元素时提前返回', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<p>no mermaid</p>')
    mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    expect(mocks.mermaidRun).not.toHaveBeenCalled()
  })

  it('getMermaid 失败时设置错误文本', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mocks.mermaidInitialize.mockImplementation(() => {
      throw new Error('init failed')
    })
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    expect(wrapper.find('.md-mermaid').text()).toContain('流程图加载失败')
  })

  it('mermaid 元素无 source 时标记为已渲染', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid"></div>')
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    const el = wrapper.find('.md-mermaid').element as HTMLElement
    expect(el.dataset.rendered).toBe('1')
  })

  it('已渲染且 source 未变化时跳过', async () => {
    // 使用空白内容 + streaming=true，使 streaming 变 false 时不触发 v-html 重渲染
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    const wrapper = mount(MessageBody, { props: { content: '   ', streaming: true } })
    await waitForFlush()
    expect(mocks.mermaidRun).toHaveBeenCalledTimes(1)
    // streaming 变 false（内容空白，rendered 不变，v-html 不重渲染）
    mocks.mermaidRun.mockClear()
    await wrapper.setProps({ streaming: false })
    await waitForFlush()
    expect(mocks.mermaidRun).not.toHaveBeenCalled()
  })

  it('第一个变体渲染成功', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mocks.mermaidRun.mockImplementation(async (opts?: Record<string, unknown>) => {
      const nodes = (opts?.nodes as HTMLElement[]) || []
      for (const n of nodes) n.innerHTML = '<svg>ok</svg>'
    })
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    expect(wrapper.find('.md-mermaid svg').exists()).toBe(true)
  })

  it('第一个变体失败，sanitized 变体成功', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mocks.sanitizeMermaid.mockImplementation((s: string) => s + '\n')
    let callCount = 0
    mocks.mermaidRun.mockImplementation(async (opts?: Record<string, unknown>) => {
      callCount++
      if (callCount === 1) throw new Error('first failed')
      const nodes = (opts?.nodes as HTMLElement[]) || []
      for (const n of nodes) n.innerHTML = '<svg>ok</svg>'
    })
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    expect(wrapper.find('.md-mermaid svg').exists()).toBe(true)
    expect(mocks.mermaidRun).toHaveBeenCalledTimes(2)
  })

  it('所有变体失败时渲染错误 UI', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mocks.sanitizeMermaid.mockImplementation((s: string) => s + '\n')
    mocks.mermaidRun.mockImplementation(async () => {
      throw new Error('parse error')
    })
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    expect(wrapper.find('.md-mermaid-fail').exists()).toBe(true)
    expect(wrapper.find('.md-mermaid-fail__msg').text()).toContain('parse error')
    expect(wrapper.find('[data-copy-source]').exists()).toBe(true)
  })

  it('sanitize 返回相同时不产生第二个变体', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mocks.sanitizeMermaid.mockImplementation((s: string) => s)
    mocks.mermaidRun.mockImplementation(async () => {
      throw new Error('fail')
    })
    mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    expect(mocks.mermaidRun).toHaveBeenCalledTimes(1)
  })

  it('错误消息中的特殊字符被转义', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mocks.mermaidRun.mockImplementation(async () => {
      throw new Error('<script>x</script>')
    })
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    const html = wrapper.find('.md-mermaid-fail__msg').html()
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })

  it('source 中的特殊字符在错误 UI 中被转义', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="a<b>&c"></div>')
    mocks.mermaidRun.mockImplementation(async () => {
      throw new Error('fail')
    })
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    const codeHtml = wrapper.find('.md-mermaid-fail .md-code__body').html()
    expect(codeHtml).toContain('&lt;')
    expect(codeHtml).toContain('&gt;')
    expect(codeHtml).toContain('&amp;')
  })

  it('lastErr 为非 Error 对象时使用 String 转换', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mocks.mermaidRun.mockImplementation(async () => {
      throw 'string error'
    })
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    expect(wrapper.find('.md-mermaid-fail__msg').text()).toContain('string error')
  })

  it('lastErr 为 undefined 时错误消息为空字符串', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mocks.mermaidRun.mockImplementation(async () => {
      throw undefined
    })
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    expect(wrapper.find('.md-mermaid-fail__msg').text()).toContain('流程图解析失败：')
  })

  it('错误 UI 复制按钮：复制成功', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mocks.mermaidRun.mockImplementation(async () => {
      throw new Error('fail')
    })
    clipboardWriteText.mockImplementation(async () => {})
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    const btn = wrapper.find('[data-copy-source]')
    await btn.trigger('click')
    await nextTick()
    await nextTick()
    expect(clipboardWriteText).toHaveBeenCalledWith('graph TD;A-->B')
    expect(btn.text()).toBe('已复制')
  })

  it('错误 UI 复制按钮：复制失败', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mocks.mermaidRun.mockImplementation(async () => {
      throw new Error('fail')
    })
    clipboardWriteText.mockImplementation(async () => {
      throw new Error('denied')
    })
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    const btn = wrapper.find('[data-copy-source]')
    await btn.trigger('click')
    await nextTick()
    await nextTick()
    expect(btn.text()).toBe('复制失败')
  })

  it('错误 UI 复制按钮成功后 1400ms 恢复原文本', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mocks.mermaidRun.mockImplementation(async () => {
      throw new Error('fail')
    })
    clipboardWriteText.mockImplementation(async () => {})
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    const btn = wrapper.find('[data-copy-source]')
    // 在点击前启用假定时器，确保 setTimeout 进入假定时器队列
    vi.useFakeTimers()
    await btn.trigger('click')
    // 等待 microtask（clipboard.writeText 的 Promise）完成
    await nextTick()
    await nextTick()
    expect(btn.text()).toBe('已复制')
    // 推进假定时器 1400ms，触发恢复回调
    vi.advanceTimersByTime(1400)
    await nextTick()
    expect(btn.text()).toBe('复制源码')
    vi.useRealTimers()
  })

  it('错误 UI 复制按钮失败后 1400ms 恢复原文本', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mocks.mermaidRun.mockImplementation(async () => {
      throw new Error('fail')
    })
    clipboardWriteText.mockImplementation(async () => {
      throw new Error('denied')
    })
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    const btn = wrapper.find('[data-copy-source]')
    // 在点击前启用假定时器，确保 setTimeout 进入假定时器队列
    vi.useFakeTimers()
    await btn.trigger('click')
    await nextTick()
    await nextTick()
    expect(btn.text()).toBe('复制失败')
    // 推进假定时器 1400ms，触发恢复回调
    vi.advanceTimersByTime(1400)
    await nextTick()
    expect(btn.text()).toBe('复制源码')
    vi.useRealTimers()
  })
})

// ─── bindCopyButtons ───────────────────────────────────────────
describe('MessageBody bindCopyButtons', () => {
  it('无复制按钮时正常执行', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<p>no code</p>')
    mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
  })

  it('绑定复制按钮并成功复制', async () => {
    mocks.renderMarkdown.mockImplementation(
      () =>
        '<div class="md-code"><div class="md-code__head"><button class="md-code__copy">复制</button></div><pre><code class="md-code__body">console.log(1)</code></pre></div>',
    )
    clipboardWriteText.mockImplementation(async () => {})
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    const btn = wrapper.find('.md-code__copy')
    expect(btn.element.dataset.bound).toBe('1')
    await btn.trigger('click')
    await nextTick()
    await nextTick()
    expect(clipboardWriteText).toHaveBeenCalledWith('console.log(1)')
    expect(btn.text()).toBe('已复制')
  })

  it('复制失败时显示失败文本', async () => {
    mocks.renderMarkdown.mockImplementation(
      () =>
        '<div class="md-code"><div class="md-code__head"><button class="md-code__copy">复制</button></div><pre><code class="md-code__body">x</code></pre></div>',
    )
    clipboardWriteText.mockImplementation(async () => {
      throw new Error('denied')
    })
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    const btn = wrapper.find('.md-code__copy')
    await btn.trigger('click')
    await nextTick()
    await nextTick()
    expect(btn.text()).toBe('复制失败')
  })

  it('已绑定的按钮不重复绑定', async () => {
    mocks.renderMarkdown.mockImplementation(
      () =>
        '<div class="md-code"><div class="md-code__head"><button class="md-code__copy">复制</button></div><pre><code class="md-code__body">x</code></pre></div>',
    )
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    // 触发再次 flush（streaming 变化）
    await wrapper.setProps({ streaming: true })
    await wrapper.setProps({ streaming: false })
    await waitForFlush()
    const btn = wrapper.find('.md-code__copy')
    expect(btn.element.dataset.bound).toBe('1')
  })

  it('复制成功后 1400ms 恢复原文本', async () => {
    mocks.renderMarkdown.mockImplementation(
      () =>
        '<div class="md-code"><div class="md-code__head"><button class="md-code__copy">复制</button></div><pre><code class="md-code__body">x</code></pre></div>',
    )
    clipboardWriteText.mockImplementation(async () => {})
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    const btn = wrapper.find('.md-code__copy')
    // 在点击前启用假定时器，确保 setTimeout 进入假定时器队列
    vi.useFakeTimers()
    await btn.trigger('click')
    await nextTick()
    await nextTick()
    expect(btn.text()).toBe('已复制')
    // 推进假定时器 1400ms，触发恢复回调
    vi.advanceTimersByTime(1400)
    await nextTick()
    expect(btn.text()).toBe('复制')
    vi.useRealTimers()
  })
})

// ─── watchers ──────────────────────────────────────────────────
describe('MessageBody watchers', () => {
  it('streaming 时 content 变化不触发后处理', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    const wrapper = mount(MessageBody, { props: { content: 'initial', streaming: true } })
    await waitForFlush()
    mocks.mermaidRun.mockClear()
    await wrapper.setProps({ content: 'updated' })
    await waitForFlush()
    expect(mocks.mermaidRun).not.toHaveBeenCalled()
  })

  it('非 streaming 时 content 变化通过 RAF 触发后处理', async () => {
    // 使用内容相关的 HTML，确保 v-html 在 content 变化时重新渲染
    mocks.renderMarkdown.mockImplementation(
      (s: string) => `<div class="md-mermaid" data-source="graph TD;${s}"></div>`,
    )
    const wrapper = mount(MessageBody, { props: { content: 'initial' } })
    await waitForFlush()
    mocks.mermaidRun.mockClear()
    await wrapper.setProps({ content: 'updated' })
    expect(rafCallback).not.toBeNull()
    flushRaf()
    await waitForFlush()
    expect(mocks.mermaidRun).toHaveBeenCalled()
  })

  it('RAF 已调度时不重复调度', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<p>test</p>')
    const wrapper = mount(MessageBody, { props: { content: 'initial' } })
    await waitForFlush()
    await wrapper.setProps({ content: 'change1' })
    const firstCb = rafCallback
    expect(firstCb).not.toBeNull()
    await wrapper.setProps({ content: 'change2' })
    expect(rafCallback).toBe(firstCb)
    flushRaf()
    await waitForFlush()
  })

  it('streaming 变为 false 时触发 flushAll', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    const wrapper = mount(MessageBody, { props: { content: 'test', streaming: true } })
    await waitForFlush()
    // onMounted 已触发初始 flushAll，清除调用记录
    mocks.mermaidRun.mockClear()
    await wrapper.setProps({ streaming: false })
    await waitForFlush()
    expect(mocks.mermaidRun).toHaveBeenCalled()
  })

  it('streaming 变 false 且有 pending RAF 时取消并 flush', async () => {
    mocks.renderMarkdown.mockImplementation(
      (s: string) => `<div class="md-mermaid" data-source="graph TD;${s}"></div>`,
    )
    const wrapper = mount(MessageBody, { props: { content: 'initial' } })
    await waitForFlush()
    // 触发 content watcher 调度 RAF
    await wrapper.setProps({ content: 'change1' })
    expect(rafCallback).not.toBeNull()
    // streaming 变 false（取消 RAF 并 flush）
    await wrapper.setProps({ streaming: true })
    await wrapper.setProps({ streaming: false })
    await waitForFlush()
    expect(mocks.mermaidRun).toHaveBeenCalled()
  })
})

// ─── onMounted ─────────────────────────────────────────────────
describe('MessageBody onMounted', () => {
  it('挂载时触发 flushAll', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    expect(mocks.mermaidRun).toHaveBeenCalled()
  })

  it('组件卸载后 flushAll 中的后处理提前返回', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    // 立即卸载，使 flushAll 中 nextTick 后 hostRef.value 为 null
    wrapper.unmount()
    await waitForFlush()
    expect(mocks.mermaidRun).not.toHaveBeenCalled()
  })
})

// ─── hashStr 间接测试（通过 srcHash 行为验证） ──────────────────
describe('MessageBody hashStr', () => {
  it('相同 source 产生相同 hash（跳过重渲染）', async () => {
    mocks.renderMarkdown.mockImplementation(() => '<div class="md-mermaid" data-source="graph TD;A-->B"></div>')
    const wrapper = mount(MessageBody, { props: { content: '   ', streaming: true } })
    await waitForFlush()
    const el = wrapper.find('.md-mermaid').element as HTMLElement
    const firstHash = el.dataset.srcHash
    expect(firstHash).toBeTruthy()
    mocks.mermaidRun.mockClear()
    await wrapper.setProps({ streaming: false })
    await waitForFlush()
    expect(mocks.mermaidRun).not.toHaveBeenCalled()
    expect(el.dataset.srcHash).toBe(firstHash)
  })

  it('不同 source 产生不同 hash（触发重渲染）', async () => {
    let source = 'graph TD;A-->B'
    mocks.renderMarkdown.mockImplementation(
      () => `<div class="md-mermaid" data-source="${source}"></div>`,
    )
    const wrapper = mount(MessageBody, { props: { content: 'test' } })
    await waitForFlush()
    const firstHash = (wrapper.find('.md-mermaid').element as HTMLElement).dataset.srcHash
    source = 'graph TD;A-->C'
    mocks.mermaidRun.mockClear()
    await wrapper.setProps({ content: 'test2' })
    flushRaf()
    await waitForFlush()
    expect(mocks.mermaidRun).toHaveBeenCalled()
    const newHash = (wrapper.find('.md-mermaid').element as HTMLElement).dataset.srcHash
    expect(newHash).not.toBe(firstHash)
  })
})

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { nextTick, ref, type Ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

let chatSessionId: Ref<string>
const sendMessageMock = vi.fn()
const syncSessionMessagesMock = vi.fn(async () => undefined)
const messagesMock = ref([])
const isLoadingMock = ref(false)
const isStreamingReplyMock = ref(false)
const loadingProgressTextMock = ref('')

vi.mock('@/composables/useChatView', () => ({
  useChatView: ({ sessionId }: { sessionId: Ref<string> }) => {
    chatSessionId = sessionId
    return {
      messages: messagesMock,
      isLoading: isLoadingMock,
      isStreamingReply: isStreamingReplyMock,
      loadingProgressText: loadingProgressTextMock,
      sendMessage: sendMessageMock,
      syncSessionMessages: syncSessionMessagesMock,
    }
  },
}))

vi.mock('@/utils/sanitizeHtml', () => ({
  sanitizeChatBubbleHtml: vi.fn((html: string) => html),
  sanitizeChatBubbleMarkdown: vi.fn((source: string) => source.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>')),
  plainTextFromChatHtml: vi.fn((html: string) => html),
}))

vi.mock('@/utils/chatStorageKeys', async importOriginal => ({
  ...await importOriginal<typeof import('@/utils/chatStorageKeys')>(),
  readAiSessionIdFromStorage: vi.fn(() => 'test-session-id'),
  writeAiSessionIdToStorage: vi.fn(),
}))

import FloatingChatAssistant from '@/components/FloatingChatAssistant.vue'
import { readAiSessionIdFromStorage, writeAiSessionIdToStorage } from '@/utils/chatStorageKeys'
enableAutoUnmount(afterEach)

function mountAssistant(propsOverrides = {}) {
  return mount(FloatingChatAssistant, {
    props: {
      visible: true,
      ...propsOverrides,
    },
    attachTo: document.body,
  })
}

async function openAssistant() {
  const wrapper = mountAssistant()
  await wrapper.get('.floating-chat-toggle').trigger('click')
  return wrapper
}

describe('FloatingChatAssistant', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(readAiSessionIdFromStorage).mockReturnValue('test-session-id')
    sendMessageMock.mockClear()
    messagesMock.value = []
    isLoadingMock.value = false
    isStreamingReplyMock.value = false
    loadingProgressTextMock.value = ''
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it.each([
    ['.floating-chat-root', {}], ['.floating-chat-toggle', {}],
    ['.floating-chat-toggle-label', { text: '小C助理' }],
    ['.floating-chat-toggle', { 'aria-label': '小C助理' }],
    ['.floating-chat-toggle-avatar img', { src: '/ai-butler-female-avatar-v1.png', draggable: 'false' }],
  ])('renders %s with its accessible defaults', (selector, expected) => {
    const element = mountAssistant().get(selector)
    for (const [attribute, value] of Object.entries(expected)) {
      expect(attribute === 'text' ? element.text() : element.attributes(attribute)).toBe(value)
    }
  })
  it('hides the root when disabled, the panel initially, and uses the admin avatar when requested', () => {
    expect(mountAssistant({ visible: false }).find('.floating-chat-root').exists()).toBe(false)
    expect(mountAssistant().find('.floating-chat-panel').exists()).toBe(false)
    expect(mountAssistant({ maleAvatar: true }).get('img').attributes('src')).toBe('/ai-butler-male-avatar-v1.jpg')
  })

  it('clicking toggle opens panel', async () => {
    const wrapper = await openAssistant()
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(true)
  })

  it('expands and collapses the native desktop window and can reopen the main window', async () => {
    const setExpanded = vi.fn(async () => undefined)
    const openMain = vi.fn(async () => undefined)
    vi.stubGlobal('xcagiDesktopAssistant', { setExpanded, openMain })
    const wrapper = mountAssistant({ desktopWindow: true })
    await wrapper.get('.floating-chat-toggle').trigger('click')
    expect(setExpanded).toHaveBeenLastCalledWith(true)
    expect(syncSessionMessagesMock).toHaveBeenCalled()
    const header = wrapper.get('.floating-chat-header').element
    const setPointerCapture = vi.fn()
    Object.assign(header, { setPointerCapture })
    const openMainButton = wrapper.get('button[aria-label="打开 XCAGI 主窗口"]')
    openMainButton.element.dispatchEvent(Object.assign(new MouseEvent('pointerdown', { bubbles: true }), { pointerId: 1 }))
    expect(setPointerCapture).not.toHaveBeenCalled()
    await openMainButton.trigger('click')
    expect(openMain).toHaveBeenCalledOnce()
    await wrapper.get('textarea').setValue('当前会话草稿')
    wrapper.vm.resetDesktopPanel()
    await nextTick()
    expect(setExpanded).toHaveBeenLastCalledWith(false)
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(false)
    await wrapper.get('.floating-chat-toggle').trigger('click')
    expect(wrapper.get('textarea').element.value).toBe('当前会话草稿')
    vi.mocked(readAiSessionIdFromStorage).mockReturnValueOnce('other-session')
    wrapper.vm.resetDesktopPanel()
    await nextTick()
    await wrapper.get('.floating-chat-toggle').trigger('click')
    expect(wrapper.get('textarea').element.value).toBe('')
  })

  it.each([false, true])('adopts the latest desktop session after loading, reopened=%s', async (reopen) => {
    vi.stubGlobal('xcagiDesktopAssistant', { setExpanded: vi.fn(async () => undefined) })
    vi.mocked(readAiSessionIdFromStorage).mockReturnValue('old-session')
    const syncedSessions: string[] = []
    syncSessionMessagesMock.mockImplementation(async () => { syncedSessions.push(chatSessionId.value) })
    const wrapper = mountAssistant({ desktopWindow: true })
    await wrapper.get('.floating-chat-toggle').trigger('click')
    await wrapper.get('textarea').setValue('old draft')
    isLoadingMock.value = true
    await nextTick()
    vi.mocked(readAiSessionIdFromStorage).mockReturnValue('next-session')
    wrapper.vm.resetDesktopPanel()
    await nextTick()
    expect(chatSessionId.value).toBe('old-session')
    if (reopen) await wrapper.get('.floating-chat-toggle').trigger('click')
    vi.mocked(readAiSessionIdFromStorage).mockReturnValue('latest-session')
    isLoadingMock.value = false
    await nextTick()
    expect(chatSessionId.value).toBe('latest-session')
    if (!reopen) await wrapper.get('.floating-chat-toggle').trigger('click')
    expect(wrapper.get('textarea').element.value).toBe('')
    expect(syncedSessions.at(-1)).toBe('latest-session')
  })

  it('clicking toggle again closes panel', async () => {
    const wrapper = await openAssistant()
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(true)
    await wrapper.find('.floating-chat-toggle').trigger('click')
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(false)
  })

  it('toggle button aria-expanded reflects open state', async () => {
    const wrapper = mountAssistant()
    expect(wrapper.find('.floating-chat-toggle').attributes('aria-expanded')).toBe('false')
    await wrapper.find('.floating-chat-toggle').trigger('click')
    expect(wrapper.find('.floating-chat-toggle').attributes('aria-expanded')).toBe('true')
  })

  it('clicking close button closes panel', async () => {
    const wrapper = await openAssistant()
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(true)
    await wrapper.find('.floating-chat-close').trigger('click')
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(false)
  })

  it('renders panel header with title', async () => {
    const wrapper = await openAssistant()
    expect(wrapper.find('.floating-chat-title').text()).toBe('小C助理')
    expect(wrapper.find('.floating-chat-subtitle').exists()).toBe(false)
  })

  it('renders textarea input with placeholder', async () => {
    const wrapper = await openAssistant()
    const textarea = wrapper.find('.floating-chat-input')
    expect(textarea.attributes('placeholder')).toBe('输入消息...')
  })

  it('send button is disabled when draft is empty', async () => {
    const wrapper = await openAssistant()
    expect(wrapper.find('.floating-chat-send').attributes('disabled')).toBeDefined()
  })

  it('send button is enabled when draft has text', async () => {
    const wrapper = await openAssistant()
    await wrapper.find('.floating-chat-input').setValue('测试消息')
    expect(wrapper.find('.floating-chat-send').attributes('disabled')).toBeUndefined()
  })

  it('send button is disabled when loading', async () => {
    const wrapper = await openAssistant()
    await wrapper.find('.floating-chat-input').setValue('测试')
    isLoadingMock.value = true
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.floating-chat-send').attributes('disabled')).toBeDefined()
  })

  it('textarea is disabled when loading', async () => {
    const wrapper = await openAssistant()
    isLoadingMock.value = true
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.floating-chat-input').attributes('disabled')).toBeDefined()
  })

  it('submitMessage sends message and clears draft', async () => {
    sendMessageMock.mockResolvedValue(undefined)
    const wrapper = await openAssistant()
    await wrapper.find('.floating-chat-input').setValue('你好')
    await wrapper.find('form').trigger('submit.prevent')
    expect(sendMessageMock).toHaveBeenCalledWith('你好')
  })

  it('submitMessage does not send empty text', async () => {
    const wrapper = await openAssistant()
    await wrapper.find('form').trigger('submit.prevent')
    expect(sendMessageMock).not.toHaveBeenCalled()
  })

  it('submitMessage does not send when loading', async () => {
    const wrapper = await openAssistant()
    await wrapper.find('.floating-chat-input').setValue('测试')
    isLoadingMock.value = true
    await wrapper.vm.$nextTick()
    await wrapper.find('form').trigger('submit.prevent')
    expect(sendMessageMock).not.toHaveBeenCalled()
  })

  it('keeps the draft when Enter confirms an IME candidate or Shift+Enter inserts a line', async () => {
    const wrapper = await openAssistant()
    const input = wrapper.get('.floating-chat-input')
    await input.setValue('中文草稿')
    for (const init of [{ isComposing: true }, { keyCode: 229 }, { shiftKey: true }]) {
      const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, ...init })
      if ('keyCode' in init) Object.defineProperty(event, 'keyCode', { configurable: true, value: 229 })
      input.element.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(false)
    }
    expect(sendMessageMock).not.toHaveBeenCalled()
    expect((input.element as HTMLTextAreaElement).value).toBe('中文草稿')
  })

  it('Enter key submits message', async () => {
    sendMessageMock.mockResolvedValue(undefined)
    const wrapper = await openAssistant()
    await wrapper.find('.floating-chat-input').setValue('回车发送')
    await wrapper.find('.floating-chat-input').trigger('keydown.enter')
    expect(sendMessageMock).toHaveBeenCalledWith('回车发送')
  })

  it('renders messages from useChatView', async () => {
    messagesMock.value = [
      { role: 'user', content: '你好', time: '10:00' },
      { role: 'ai', content: '你好！', time: '10:01' },
    ]
    const wrapper = await openAssistant()
    const msgs = wrapper.findAll('.floating-chat-message')
    expect(msgs).toHaveLength(2)
    expect(msgs[0].classes()).toContain('user')
    expect(msgs[1].classes()).toContain('ai')
  })

  it('follows streamed text only while the reader remains near the latest message', async () => {
    messagesMock.value = [{ role: 'ai', content: '第一段', time: '10:01' }]
    const wrapper = await openAssistant()
    await flushPromises()
    const host = wrapper.get('.floating-chat-messages')
    const element = host.element as HTMLElement
    let height = 600
    Object.defineProperty(element, 'scrollHeight', { configurable: true, get: () => height })
    Object.defineProperty(element, 'clientHeight', { configurable: true, get: () => 200 })
    element.scrollTop = 80
    await host.trigger('scroll')
    height = 700
    messagesMock.value = [{ role: 'ai', content: '第一段 第二段', time: '10:01' }]
    await flushPromises()
    expect(element.scrollTop).toBe(80)
    element.scrollTop = 500
    await host.trigger('scroll')
    height = 800
    messagesMock.value = [{ role: 'ai', content: '第一段 第二段 第三段', time: '10:01' }]
    await flushPromises()
    expect(element.scrollTop).toBe(800)
  })

  it('renders assistant Markdown with shared MessageBody instead of a raw HTML bubble', async () => {
    messagesMock.value = [{ role: 'ai', content: '**核对完成**', time: '10:01' }]
    const wrapper = await openAssistant()
    await flushPromises()
    expect(wrapper.get('.floating-chat-bubble .msg-body strong').text()).toBe('核对完成')
  })

  it('shows loading message when isLoading and not streaming', async () => {
    isLoadingMock.value = true
    isStreamingReplyMock.value = false
    loadingProgressTextMock.value = '正在思考...'
    const wrapper = await openAssistant()
    await wrapper.vm.$nextTick()
    const loadingMsg = wrapper.findAll('.floating-chat-message.ai')
    const lastMsg = loadingMsg[loadingMsg.length - 1]
    expect(lastMsg.find('.floating-chat-bubble').text()).toBe('正在思考...')
  })

  it('does not show loading message when streaming', async () => {
    isLoadingMock.value = true
    isStreamingReplyMock.value = true
    const wrapper = await openAssistant()
    await wrapper.vm.$nextTick()
    // No extra loading message should be added
    const msgs = wrapper.findAll('.floating-chat-message')
    expect(msgs).toHaveLength(0)
  })

  it('limits visible messages to 20', async () => {
    const manyMessages = Array.from({ length: 25 }, (_, i) => ({
      role: 'user',
      content: `消息${i}`,
      time: '10:00',
    }))
    messagesMock.value = manyMessages
    const wrapper = await openAssistant()
    expect(wrapper.findAll('.floating-chat-message')).toHaveLength(20)
  })

  it('rootStyle contains left and top positions', () => {
    const wrapper = mountAssistant()
    const style = wrapper.find('.floating-chat-root').attributes('style') || ''
    expect(style).toContain('left:')
    expect(style).toContain('top:')
  })

  it.each(['xcagi:close-floating-chat', 'xcagi:close-assistant-float'])('responds to %s', async (event) => {
    const wrapper = await openAssistant()
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(true)
    window.dispatchEvent(new Event(event))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(false)
  })

  it('responds to xcagi:suppress-floating-chat event', async () => {
    const wrapper = await openAssistant()
    window.dispatchEvent(new Event('xcagi:suppress-floating-chat'))
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.floating-chat-root').exists()).toBe(false)
  })

  it('responds to xcagi:restore-floating-chat event', async () => {
    const wrapper = mountAssistant()
    window.dispatchEvent(new Event('xcagi:suppress-floating-chat'))
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.floating-chat-root').exists()).toBe(false)
    window.dispatchEvent(new Event('xcagi:restore-floating-chat'))
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.floating-chat-root').exists()).toBe(true)
  })

  it('renders message time', async () => {
    messagesMock.value = [{ role: 'user', content: '测试', time: '14:30' }]
    const wrapper = await openAssistant()
    expect(wrapper.find('.floating-chat-time').text()).toBe('14:30')
  })

  it('generates and persists a session when storage is empty', () => {
    vi.mocked(readAiSessionIdFromStorage).mockReturnValueOnce('')
    mountAssistant()
    expect(writeAiSessionIdToStorage).toHaveBeenCalledWith(expect.stringMatching(/^[a-z0-9]+$/))
  })

  it('drags the desktop avatar in screen coordinates and keeps its next click usable', async () => {
    const moveWindow = vi.fn(async () => undefined)
    const setExpanded = vi.fn(async () => undefined)
    vi.stubGlobal('xcagiDesktopAssistant', { moveWindow, setExpanded })
    const wrapper = mountAssistant({ desktopWindow: true })
    const toggle = wrapper.get('.floating-chat-toggle')
    const element = toggle.element
    Object.assign(element, { setPointerCapture: vi.fn(), hasPointerCapture: () => false })
    const pointer = (kind: string, screenX: number, screenY: number) => {
      element.dispatchEvent(Object.assign(new MouseEvent(kind, { screenX, screenY, bubbles: true }), { pointerId: 1 }))
    }
    pointer('pointerdown', 40, 30)
    pointer('pointermove', 42, 32)
    expect(moveWindow).not.toHaveBeenCalled()
    pointer('pointermove', 112, 90)
    expect(moveWindow).toHaveBeenLastCalledWith(window.screenX + 72, window.screenY + 60)
    pointer('pointerup', 112, 90)
    await toggle.trigger('click')
    expect(setExpanded).not.toHaveBeenCalled()
    pointer('pointerdown', 112, 90)
    pointer('pointerup', 112, 90)
    await toggle.trigger('click')
    expect(setExpanded).toHaveBeenLastCalledWith(true)
  })

  it('drags only the active primary pointer, clamps to the viewport and suppresses one post-drag click', async () => {
    const wrapper = mountAssistant()
    await flushPromises()
    const toggle = wrapper.get('.floating-chat-toggle')
    const root = wrapper.get('.floating-chat-root')
    const el = toggle.element as HTMLElement
    const capture = vi.fn(), release = vi.fn()
    Object.assign(el, { setPointerCapture: capture, hasPointerCapture: () => true, releasePointerCapture: release })
    const pointer = async (kind: string, properties: PointerEventInit = {}) => {
      const { pointerId = 7, ...mouse } = properties
      const event = new MouseEvent(kind, { bubbles: true, button: 0, clientX: 100, clientY: 100, ...mouse })
      el.dispatchEvent(Object.assign(event, { pointerId }))
      await nextTick()
    }
    await pointer('pointerdown', { button: 2 })
    expect(capture).not.toHaveBeenCalled()
    await pointer('pointerdown')
    expect(capture).toHaveBeenCalledWith(7)
    const initial = root.attributes('style')
    await pointer('pointermove', { pointerId: 8, clientX: 200 })
    await pointer('pointermove', { clientX: 102 })
    expect(root.attributes('style')).toBe(initial)
    expect(root.classes()).not.toContain('dragging')
    await pointer('pointermove', { clientX: -5000, clientY: -5000 })
    expect(root.classes()).toContain('dragging')
    expect(root.attributes('style')).toContain('left: 8px; top: 8px')
    await pointer('pointermove', { clientX: 5000, clientY: 5000 })
    expect(root.attributes('style')).toContain(`left: ${window.innerWidth - 8}px`)
    await pointer('pointerup')
    expect(release).toHaveBeenCalledWith(7)
    expect(root.classes()).not.toContain('dragging')
    await toggle.trigger('click')
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(false)
    await toggle.trigger('click')
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(true)
    await pointer('pointerdown')
    await pointer('pointercancel')
    await toggle.trigger('click')
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(false)
  })

  it('repositions after visibility changes, scrolls new messages and removes window handlers on unmount', async () => {
    const wrapper = await openAssistant()
    const list = wrapper.get('.floating-chat-messages').element as HTMLElement
    Object.defineProperty(list, 'scrollHeight', { value: 240 })
    messagesMock.value = [{ role: 'ai', content: '新回复', time: '12:00' }]
    await flushPromises()
    expect(list.scrollTop).toBe(240)
    const remove = vi.spyOn(window, 'removeEventListener')
    await wrapper.setProps({ visible: false })
    window.dispatchEvent(new Event('resize'))
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(wrapper.get('.floating-chat-root').attributes('style')).toContain(`left: ${window.innerWidth - 22}px`)
    wrapper.unmount()
    for (const event of ['resize', 'xcagi:close-floating-chat', 'xcagi:close-assistant-float', 'xcagi:suppress-floating-chat', 'xcagi:restore-floating-chat']) {
      expect(remove).toHaveBeenCalledWith(event, expect.any(Function))
    }
  })
})

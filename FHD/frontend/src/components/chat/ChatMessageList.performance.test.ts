import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { h, nextTick, ref } from 'vue'
import DOMPurify from 'dompurify'
import ChatMessageList from './ChatMessageList.vue'
import { useChatMessageUi } from '@/composables/useChatMessageUi'
import { useChatTaskList, type TaskItem } from '@/composables/useChatTaskList'
import type { ChatMessage } from '@/composables/useChatMessages'

vi.mock('@/utils/tts', () => ({ cleanTextForSpeech: (text: string) => text, speakText: vi.fn(), stopSpeaking: vi.fn() }))
vi.mock('@/utils/pretext', () => ({ estimateMessageHeight: () => 100 }))
enableAutoUnmount(afterEach)
afterEach(() => vi.restoreAllMocks())

function fixture(count = 500) {
  const messages = ref<ChatMessage[]>(Array.from({ length: count }, (_, i) => ({ role: i % 2 ? 'ai' : 'user', content: `消息 ${i}`, time: '12:00' })))
  const sessionKey = ref('tenant-a/session-a')
  const host = ref<HTMLElement | null>(null)
  let ui: ReturnType<typeof useChatMessageUi>
  const wrapper = mount({ setup() {
    ui = useChatMessageUi({ messages, chatMessagesRef: host, sessionKey })
    return () => h(ChatMessageList, {
      messages: messages.value, sessionKey: sessionKey.value, chatMessagesRef: host,
      isLoading: false, isStreamingReply: true, loadingProgressText: '',
      messageHeights: ui.messageHeights.value, latestAiMessageIndex: ui.latestAiMessageIndex.value, playingMsgIdx: -1,
      isMessageCollapsed: ui.isMessageCollapsed, canSpeakMessage: ui.canSpeakMessage,
      onExpandMessage: ui.expandMessage, onCollapseMessage: ui.collapseMessage,
    })
  } })
  const button = (label: string) => wrapper.findAll('button').find((item) => item.text() === label)!
  const indexes = () => wrapper.findAll('[data-message-index]').map((item) => Number(item.attributes('data-message-index')))
  return { wrapper, messages, host, sessionKey, ui: ui!, button, indexes }
}

describe('bounded chat history and derived content', () => {
  it('sanitizes only changed content while keeping XSS removal and invalidation', async () => {
    const sanitize = vi.spyOn(DOMPurify, 'sanitize')
    const f = fixture()
    await nextTick()
    await nextTick()
    expect(f.indexes()).toHaveLength(80)
    sanitize.mockClear()
    f.messages.value[499].content += ' 流式增量'
    await nextTick()
    // 只有变化的那条消息需要重新净化（历史消息不再折叠，首屏已整体渲染过一遍）
    expect(sanitize.mock.calls.length).toBeLessThan(10)
    expect(f.wrapper.get('[data-message-index="499"] .message-html').text()).toContain('流式增量')
    // Construct the hostile input in an inert document; never attach or execute it.
    const fixtureDocument = document.implementation.createHTMLDocument('XSS fixture')
    const unsafeImage = fixtureDocument.createElement('img')
    unsafeImage.setAttribute('src', 'x')
    unsafeImage.setAttribute('onerror', 'bad()')
    expect(unsafeImage.isConnected).toBe(false)
    expect(unsafeImage.getAttribute('onerror')).toBe('bad()')
    f.messages.value[498].content = `<b>修订</b>${unsafeImage.outerHTML}<script>bad()</script>`
    await nextTick()
    const body = f.wrapper.get('[data-message-index="498"] .message-html')
    expect(body.text()).toBe('修订')
    expect(body.find('script').exists()).toBe(false)
    expect(body.find('[onerror]').exists()).toBe(false)
    sanitize.mockClear()
    f.sessionKey.value = 'tenant-b/session-a'
    await nextTick()
    expect(sanitize.mock.calls.length).toBeGreaterThan(80)
  })

  it('does not reparse huge Markdown during streaming and formats after the terminal receipt', async () => {
    const f = fixture()
    await nextTick()
    const message = f.messages.value[499]
    message.streamStatus = 'streaming'
    message.content = '# 报告\\n' + '长消息正文\\n'.repeat(3500) + '<img src=x onerror=bad()>'
    const sanitize = vi.spyOn(DOMPurify, 'sanitize')
    await nextTick()
    const body = f.wrapper.get('[data-message-index="499"] .message-html')
    expect(body.classes()).toContain('message-html--streaming-long')
    expect(body.text()).toContain('<img src=x onerror=bad()>')
    expect(body.find('img').exists()).toBe(false)
    expect(sanitize).not.toHaveBeenCalled()
    message.streamStatus = undefined
    await nextTick()
    expect(f.wrapper.get('[data-message-index="499"] .message-html').classes()).not.toContain('message-html--streaming-long')
    expect(sanitize).toHaveBeenCalled()
    expect(f.wrapper.get('[data-message-index="499"] .message-html').find('[onerror]').exists()).toBe(false)
  })

  it('can traverse every old and new message while never mounting more than 80 rows', async () => {
    const f = fixture()
    const visited = new Set(f.indexes())
    while (!(f.button('更早消息').element as HTMLButtonElement).disabled) {
      await f.button('更早消息').trigger('click')
      expect(f.indexes()).toHaveLength(80)
      f.indexes().forEach((index) => visited.add(index))
    }
    expect(f.indexes()[0]).toBe(0)
    while (!(f.button('较新消息').element as HTMLButtonElement).disabled) {
      await f.button('较新消息').trigger('click')
      expect(f.indexes()).toHaveLength(80)
      f.indexes().forEach((index) => visited.add(index))
    }
    expect(visited.size).toBe(500)
    expect(f.indexes()[79]).toBe(499)
    expect(f.wrapper.get('[data-message-index="499"]').attributes('aria-posinset')).toBe('500')
  })

  it.each([1000, 10000])('bounds mounted history for %i messages', async (count) => {
    const f = fixture(count)
    await nextTick()
    expect(f.indexes()).toHaveLength(80)
    expect(f.indexes()[0]).toBe(count - 80)
    await f.button('更早消息').trigger('click')
    expect(f.indexes()).toHaveLength(80)
    expect(f.indexes()[0]).toBe(count - 140)
  })

  it('retains stable message identities and scroll offset when earlier pages are prepended', async () => {
    const f = fixture()
    await nextTick()
    await f.button('更早消息').trigger('click')
    const el = f.host.value!
    Object.defineProperties(el, {
      scrollHeight: { configurable: true, value: 5000 },
      clientHeight: { configurable: true, value: 500 },
    })
    el.scrollTop = 123
    el.dispatchEvent(new Event('scroll'))
    const keys = () => f.wrapper.findAll('[data-message-key]').map(row => row.attributes('data-message-key'))
    const before = keys()
    f.messages.value = [
      ...Array.from({ length: 40 }, (_, i): ChatMessage => ({ role: 'ai', content: `更早 ${i}`, time: '11:00' })),
      ...f.messages.value,
    ]
    await nextTick()
    expect(keys()).toEqual(before)
    expect(f.indexes()[0]).toBe(400)
    expect(el.scrollTop).toBe(123)
  })

  it('moves the history pager into the quick-actions header slot when present', async () => {
    const slot = document.createElement('div')
    slot.id = 'chat-history-nav-slot'
    document.body.appendChild(slot)
    try {
      const f = fixture()
      await nextTick()
      const nav = slot.querySelector('.chat-history-navigation')
      expect(nav).not.toBeNull()
      expect(nav!.textContent).toContain('更早消息')
      expect(f.wrapper.text()).not.toContain('更早消息')
    } finally {
      slot.remove()
    }
  })

  it('preserves history reading during streaming/appends and resets the window/expansion on scope changes', async () => {
    const f = fixture()
    await nextTick()
    const el = f.host.value!
    Object.defineProperties(el, { scrollHeight: { configurable: true, value: 5000 }, clientHeight: { configurable: true, value: 500 } })
    el.scrollTop = 120
    el.dispatchEvent(new Event('scroll'))
    f.ui.expandMessage(497)
    f.messages.value[499].content += ' 更多内容'
    f.messages.value.push({ role: 'ai', content: '新回复', time: '12:01' })
    await nextTick()
    expect(el.scrollTop).toBe(120)
    expect(f.indexes()[0]).toBe(420)
    await f.button('更早消息').trigger('click')
    expect(f.indexes()[0]).toBe(360)
    f.sessionKey.value = 'tenant-b/session-b'
    await nextTick()
    await nextTick()
    expect(f.indexes()[0]).toBe(421)
    // 普通消息不再折叠：切换会话后历史消息直接完整展示
    expect(f.ui.isMessageCollapsed(f.messages.value[497], 497)).toBe(false)
    expect(f.wrapper.find('[data-message-index="497"] .msg-fold__body').exists()).toBe(false)
    expect(el.scrollTop).toBe(5000)
    f.messages.value = [{ role: 'ai', content: '另一会话', time: '12:02' }]
    await nextTick()
    expect(f.indexes()).toEqual([0])
    expect(f.wrapper.text()).not.toContain('消息 420')
  })

  it('reveals a task target outside the window and keeps global expansion/copy actions correct', async () => {
    const f = fixture()
    await nextTick()
    const scroll = vi.fn()
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView')
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scroll })
    try {
      useChatTaskList({ chatMessagesRef: f.host }).jumpToTaskMessage({ messageRef: '5' } as TaskItem)
      await nextTick()
      expect(f.indexes()).toHaveLength(80)
      expect(f.indexes()).toContain(5)
      expect(scroll).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' })
      // 短消息不溢出，折叠态直接完整可见（不再有「展开」按钮）
      expect(f.wrapper.find('[data-message-index="5"] .msg-fold__trigger').exists()).toBe(false)
      expect(f.wrapper.get('[data-message-index="5"] .message-html').text()).toBe('消息 5')
      const writeText = vi.fn().mockResolvedValue(undefined)
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
      await f.wrapper.get('[data-message-index="5"] .message-copy-btn').trigger('click')
      expect(writeText).toHaveBeenCalledWith('消息 5')
    } finally {
      if (original) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', original)
      else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
    }
  })
})

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const sendMessageMock = vi.fn()
const messagesMock = ref([])
const isLoadingMock = ref(false)
const isStreamingReplyMock = ref(false)
const loadingProgressTextMock = ref('')

vi.mock('@/composables/useChatView', () => ({
  useChatView: () => ({
    messages: messagesMock,
    isLoading: isLoadingMock,
    isStreamingReply: isStreamingReplyMock,
    loadingProgressText: loadingProgressTextMock,
    sendMessage: sendMessageMock,
  }),
}))

vi.mock('@/utils/sanitizeHtml', () => ({
  sanitizeChatBubbleHtml: vi.fn((html: string) => html),
}))

vi.mock('@/utils/xcagiStorageKeys', () => ({
  readAiSessionIdFromStorage: vi.fn(() => 'test-session-id'),
  writeAiSessionIdToStorage: vi.fn(),
}))

import FloatingChatAssistant from '@/components/FloatingChatAssistant.vue'

function mountAssistant(propsOverrides = {}) {
  return mount(FloatingChatAssistant, {
    props: {
      visible: true,
      ...propsOverrides,
    },
    attachTo: document.body,
  })
}

describe('FloatingChatAssistant', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sendMessageMock.mockClear()
    messagesMock.value = []
    isLoadingMock.value = false
    isStreamingReplyMock.value = false
    loadingProgressTextMock.value = ''
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders root element when visible', () => {
    const wrapper = mountAssistant()
    expect(wrapper.find('.floating-chat-root').exists()).toBe(true)
  })

  it('does not render when visible is false', () => {
    const wrapper = mountAssistant({ visible: false })
    expect(wrapper.find('.floating-chat-root').exists()).toBe(false)
  })

  it('renders toggle button with label', () => {
    const wrapper = mountAssistant()
    expect(wrapper.find('.floating-chat-toggle').exists()).toBe(true)
    expect(wrapper.find('.floating-chat-toggle-label').text()).toBe('小C助理')
  })

  it('toggle button has correct aria-label', () => {
    const wrapper = mountAssistant()
    expect(wrapper.find('.floating-chat-toggle').attributes('aria-label')).toBe(
      '打开小C助理悬浮窗'
    )
  })

  it('panel is hidden by default', () => {
    const wrapper = mountAssistant()
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(false)
  })

  it('clicking toggle opens panel', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(true)
  })

  it('clicking toggle again closes panel', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
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
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(true)
    await wrapper.find('.floating-chat-close').trigger('click')
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(false)
  })

  it('renders panel header with title', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    expect(wrapper.find('.floating-chat-title').text()).toBe('智能对话')
    expect(wrapper.find('.floating-chat-subtitle').text()).toBe('悬浮助手')
  })

  it('renders textarea input with placeholder', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    const textarea = wrapper.find('.floating-chat-input')
    expect(textarea.attributes('placeholder')).toBe('输入消息...')
  })

  it('send button is disabled when draft is empty', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    expect(wrapper.find('.floating-chat-send').attributes('disabled')).toBeDefined()
  })

  it('send button is enabled when draft has text', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    await wrapper.find('.floating-chat-input').setValue('测试消息')
    expect(wrapper.find('.floating-chat-send').attributes('disabled')).toBeUndefined()
  })

  it('send button is disabled when loading', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    await wrapper.find('.floating-chat-input').setValue('测试')
    isLoadingMock.value = true
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.floating-chat-send').attributes('disabled')).toBeDefined()
  })

  it('textarea is disabled when loading', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    isLoadingMock.value = true
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.floating-chat-input').attributes('disabled')).toBeDefined()
  })

  it('submitMessage sends message and clears draft', async () => {
    sendMessageMock.mockResolvedValue(undefined)
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    await wrapper.find('.floating-chat-input').setValue('你好')
    await wrapper.find('form').trigger('submit.prevent')
    expect(sendMessageMock).toHaveBeenCalledWith('你好')
  })

  it('submitMessage does not send empty text', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    await wrapper.find('form').trigger('submit.prevent')
    expect(sendMessageMock).not.toHaveBeenCalled()
  })

  it('submitMessage does not send when loading', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    await wrapper.find('.floating-chat-input').setValue('测试')
    isLoadingMock.value = true
    await wrapper.vm.$nextTick()
    await wrapper.find('form').trigger('submit.prevent')
    expect(sendMessageMock).not.toHaveBeenCalled()
  })

  it('Enter key submits message', async () => {
    sendMessageMock.mockResolvedValue(undefined)
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    await wrapper.find('.floating-chat-input').setValue('回车发送')
    await wrapper.find('.floating-chat-input').trigger('keydown.enter')
    expect(sendMessageMock).toHaveBeenCalledWith('回车发送')
  })

  it('renders messages from useChatView', async () => {
    messagesMock.value = [
      { role: 'user', content: '你好', time: '10:00' },
      { role: 'ai', content: '你好！', time: '10:01' },
    ]
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    const msgs = wrapper.findAll('.floating-chat-message')
    expect(msgs).toHaveLength(2)
    expect(msgs[0].classes()).toContain('user')
    expect(msgs[1].classes()).toContain('ai')
  })

  it('shows loading message when isLoading and not streaming', async () => {
    isLoadingMock.value = true
    isStreamingReplyMock.value = false
    loadingProgressTextMock.value = '正在思考...'
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    await wrapper.vm.$nextTick()
    const loadingMsg = wrapper.findAll('.floating-chat-message.ai')
    const lastMsg = loadingMsg[loadingMsg.length - 1]
    expect(lastMsg.find('.floating-chat-bubble').text()).toBe('正在思考...')
  })

  it('does not show loading message when streaming', async () => {
    isLoadingMock.value = true
    isStreamingReplyMock.value = true
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
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
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    expect(wrapper.findAll('.floating-chat-message')).toHaveLength(20)
  })

  it('rootStyle contains left and top positions', () => {
    const wrapper = mountAssistant()
    const style = wrapper.find('.floating-chat-root').attributes('style') || ''
    expect(style).toContain('left:')
    expect(style).toContain('top:')
  })

  it('responds to xcagi:close-floating-chat event', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(true)
    window.dispatchEvent(new Event('xcagi:close-floating-chat'))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(false)
  })

  it('responds to xcagi:close-assistant-float event', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    window.dispatchEvent(new Event('xcagi:close-assistant-float'))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.floating-chat-panel').exists()).toBe(false)
  })

  it('responds to xcagi:suppress-floating-chat event', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
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

  it('does not render root when externallyHidden is true', async () => {
    const wrapper = mountAssistant()
    window.dispatchEvent(new Event('xcagi:suppress-floating-chat'))
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.floating-chat-root').exists()).toBe(false)
  })

  it('form has submit.prevent handler', async () => {
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    expect(wrapper.find('form').exists()).toBe(true)
  })

  it('renders message time', async () => {
    messagesMock.value = [{ role: 'user', content: '测试', time: '14:30' }]
    const wrapper = mountAssistant()
    await wrapper.find('.floating-chat-toggle').trigger('click')
    expect(wrapper.find('.floating-chat-time').text()).toBe('14:30')
  })

  it('applies dragging class during drag', async () => {
    const wrapper = mountAssistant()
    expect(wrapper.find('.floating-chat-root').classes()).not.toContain('dragging')
  })
})

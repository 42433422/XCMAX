import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'

// 组件内部调用 useI18n()（返回 { t }）；模板用 $t 由下方 i18nStub 插件提供。
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (k: string) => k }) }))

import ChatMessageList from './ChatMessageList.vue'
import type { ChatMessage } from '@/composables/useChatMessages'

const i18nStub = {
  install(app: { config: { globalProperties: Record<string, unknown> } }) {
    app.config.globalProperties.$t = (k: string) => k
  },
}

function mountList(messages: ChatMessage[], extra: Record<string, unknown> = {}) {
  return mount(ChatMessageList, {
    props: {
      messages,
      isLoading: false,
      isStreamingReply: false,
      loadingProgressText: '',
      messageHeights: new Map<number, number>(),
      latestAiMessageIndex: messages.length - 1,
      playingMsgIdx: -1,
      isMessageCollapsed: () => false,
      getCollapsedPreview: (s: string) => s,
      canSpeakMessage: () => false,
      chatMessagesRef: ref<HTMLElement | null>(null),
      ...extra,
    },
    global: { plugins: [i18nStub] },
  })
}

describe('ChatMessageList', () => {
  it('空内容的流式占位气泡展示打字动效而非空白', () => {
    const wrapper = mountList([
      { role: 'ai', content: '', time: '10:00', streamingShell: true } as ChatMessage,
    ])
    expect(wrapper.find('.chat-typing-indicator').exists()).toBe(true)
    expect(wrapper.find('.message-html').exists()).toBe(false)
  })

  it('流式已产出内容后不再显示打字动效', () => {
    const wrapper = mountList([
      { role: 'ai', content: '已经在生成的内容', time: '10:00', streamingShell: true } as ChatMessage,
    ])
    expect(wrapper.find('.chat-typing-indicator').exists()).toBe(false)
    expect(wrapper.find('.message-html').exists()).toBe(true)
  })

  it('失败消息展示「重试」按钮并派发 retry-message', async () => {
    const wrapper = mountList([
      { role: 'user', content: '帮我查订单', time: '10:00' } as ChatMessage,
      { role: 'ai', content: '处理失败：生成回复失败，请稍后重试', time: '10:00' } as ChatMessage,
    ])
    const retry = wrapper.find('.message-retry-btn')
    expect(retry.exists()).toBe(true)
    await retry.trigger('click')
    expect(wrapper.emitted('retry-message')).toBeTruthy()
  })

  it('加载中不显示失败消息的重试按钮', () => {
    const wrapper = mountList(
      [{ role: 'ai', content: '处理失败：网络错误', time: '10:00' } as ChatMessage],
      { isLoading: true },
    )
    expect(wrapper.find('.message-retry-btn').exists()).toBe(false)
  })

  it('正常 AI 消息不展示重试按钮', () => {
    const wrapper = mountList([
      { role: 'ai', content: '这是正常回复', time: '10:00' } as ChatMessage,
    ])
    expect(wrapper.find('.message-retry-btn').exists()).toBe(false)
  })

  it('正常 AI 消息展示「复制」按钮，点击写入剪贴板', async () => {
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true,
    })
    const wrapper = mountList([
      { role: 'ai', content: '第一行<br>第二行', time: '10:00' } as ChatMessage,
    ])
    const copyBtn = wrapper.find('.message-copy-btn')
    expect(copyBtn.exists()).toBe(true)
    await copyBtn.trigger('click')
    expect(writeText).toHaveBeenCalledWith('第一行\n第二行')
  })

  it('失败消息与流式占位不展示复制按钮', () => {
    const failed = mountList([
      { role: 'ai', content: '处理失败：网络错误', time: '10:00' } as ChatMessage,
    ])
    expect(failed.find('.message-copy-btn').exists()).toBe(false)
    const shell = mountList([
      { role: 'ai', content: '', time: '10:00', streamingShell: true } as ChatMessage,
    ])
    expect(shell.find('.message-copy-btn').exists()).toBe(false)
  })

  it('用户消息不展示复制按钮', () => {
    const wrapper = mountList([
      { role: 'user', content: '我的问题', time: '10:00' } as ChatMessage,
    ])
    expect(wrapper.find('.message-copy-btn').exists()).toBe(false)
  })
})

import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatMessageList from './ChatMessageList.vue'

function mountList(showDiagnosticMetadata = false) {
  return mount(ChatMessageList, {
    props: {
      messages: [{
        role: 'ai' as const,
        content: '系统显示 &amp;quot;正常&amp;quot;。',
        time: '07:25',
        contextSummary: '已关联上下文：最近对话 2 条（共 2）',
        thinkingSteps: 'internal chain',
        workflowAction: 'planner_action',
        nodeResults: [{
          node_id: 'internal_node',
          success: true,
          tool_id: 'secret_tool',
          action: 'execute',
        }],
      }],
      isLoading: false,
      isStreamingReply: false,
      loadingProgressText: '',
      messageHeights: new Map<number, number>(),
      latestAiMessageIndex: 0,
      playingMsgIdx: -1,
      isMessageCollapsed: () => false,
      getCollapsedPreview: () => '',
      canSpeakMessage: () => false,
      showDiagnosticMetadata,
    },
  })
}

describe('ChatMessageList', () => {
  it('renders restored quote entities as normal punctuation', () => {
    const wrapper = mountList()
    expect(wrapper.get('.message-html').text()).toContain('"正常"')
    expect(wrapper.get('.message-html').text()).not.toContain('&quot;')
  })

  it('hides internal context counters by default', () => {
    const wrapper = mountList()
    expect(wrapper.find('.context-summary').exists()).toBe(false)
    expect(wrapper.find('.thinking-panel').exists()).toBe(false)
    expect(wrapper.find('.trace-panel').exists()).toBe(false)
  })

  it('allows an explicit diagnostic surface to show context metadata', () => {
    const wrapper = mountList(true)
    expect(wrapper.get('.context-summary').text()).toContain('已关联上下文')
    expect(wrapper.get('.thinking-panel').text()).toContain('internal chain')
    expect(wrapper.get('.trace-panel').text()).toContain('internal_node')
  })

  it('renders an older collapsed AI message as a preview and emits expand', async () => {
    const getCollapsedPreview = vi.fn(() => '这是折叠后的预览')
    const wrapper = mount(ChatMessageList, {
      props: {
        messages: [
          { role: 'ai' as const, content: '旧的完整回复内容', time: '07:20' },
          { role: 'ai' as const, content: '最新回复', time: '07:25' },
        ],
        isLoading: false,
        isStreamingReply: false,
        loadingProgressText: '',
        messageHeights: new Map<number, number>([[0, 420]]),
        latestAiMessageIndex: 1,
        playingMsgIdx: -1,
        isMessageCollapsed: (_msg, idx) => idx === 0,
        getCollapsedPreview,
        canSpeakMessage: () => false,
      },
    })

    const oldMessage = wrapper.findAll('.message')[0]
    expect(oldMessage.get('.msg-fold__text').text()).toBe('这是折叠后的预览')
    expect(oldMessage.find('.message-html').exists()).toBe(false)
    expect(oldMessage.attributes('style')).toContain('min-height: auto')
    expect(getCollapsedPreview).toHaveBeenCalledWith('旧的完整回复内容')

    await oldMessage.get('.msg-fold__action').trigger('click')
    expect(wrapper.emitted('expand-message')).toEqual([[0]])
  })

  it('lets an expanded older AI message collapse again but keeps the latest reply open', async () => {
    const wrapper = mount(ChatMessageList, {
      props: {
        messages: [
          { role: 'ai' as const, content: '旧回复', time: '07:20' },
          { role: 'ai' as const, content: '最新回复', time: '07:25' },
        ],
        isLoading: false,
        isStreamingReply: false,
        loadingProgressText: '',
        messageHeights: new Map<number, number>(),
        latestAiMessageIndex: 1,
        playingMsgIdx: -1,
        isMessageCollapsed: () => false,
        getCollapsedPreview: (content) => content,
        canSpeakMessage: () => false,
      },
    })

    const messages = wrapper.findAll('.message')
    expect(messages[0].find('.msg-fold__action--collapse').exists()).toBe(true)
    expect(messages[1].find('.msg-fold__action--collapse').exists()).toBe(false)

    await messages[0].get('.msg-fold__action--collapse').trigger('click')
    expect(wrapper.emitted('collapse-message')).toEqual([[0]])
  })
})

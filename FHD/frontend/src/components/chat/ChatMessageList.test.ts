import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatMessageList from './ChatMessageList.vue'
import type { ChatMessage } from '@/composables/useChatMessages'

function mountList(showDiagnosticMetadata = false, messages?: ChatMessage[]) {
  return mount(ChatMessageList, {
    props: {
      messages: messages || [{
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

  it('does not render avatars for user messages', () => {
    const wrapper = mountList(false, [{
      role: 'user',
      content: '帮我分析这个表格',
      time: '07:26',
    }])
    expect(wrapper.find('.message-avatar').exists()).toBe(false)
    expect(wrapper.get('.message.user .message-html').text()).toContain('帮我分析这个表格')
  })
})

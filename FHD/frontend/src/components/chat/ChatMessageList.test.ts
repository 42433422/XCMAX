import { describe, expect, it } from 'vitest'
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

  it('renders a visible execution timeline for a streaming shell', () => {
    const wrapper = mount(ChatMessageList, {
      props: {
        messages: [{
          role: 'ai' as const,
          content: '',
          time: '08:00',
          streamingShell: true,
          toolProgressLabel: '正在调用客户资料…',
          executionProgress: [{
            phase: 'query',
            label: '正在调用客户资料…',
            status: 'running' as const,
            at: '2026-08-01T08:00:00.000Z',
          }],
        }],
        isLoading: true,
        isStreamingReply: true,
        loadingProgressText: '正在调用客户资料…',
        messageHeights: new Map<number, number>(),
        latestAiMessageIndex: 0,
        playingMsgIdx: -1,
        isMessageCollapsed: () => false,
        getCollapsedPreview: () => '',
        canSpeakMessage: () => false,
      },
    })
    expect(wrapper.get('.execution-timeline').text()).toContain('正在调用客户资料')
    expect(wrapper.find('.execution-timeline__spinner').exists()).toBe(true)
  })
})

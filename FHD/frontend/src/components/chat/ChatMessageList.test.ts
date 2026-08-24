import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatMessageList from './ChatMessageList.vue'

function mountList(showDiagnosticMetadata = false) {
  return mount(ChatMessageList, {
    props: {
      messages: [
        {
          role: 'ai' as const,
          content: '系统显示 &amp;quot;正常&amp;quot;。',
          time: '07:25',
          contextSummary: '已关联上下文：最近对话 2 条（共 2）',
          thinkingSteps: 'internal chain',
          workflowAction: 'planner_action',
          nodeResults: [
            {
              node_id: 'internal_node',
              success: true,
              tool_id: 'secret_tool',
              action: 'execute',
            },
          ],
        },
      ],
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

  it('renders three AI decision options and emits the selected conversation action', async () => {
    const wrapper = mount(ChatMessageList, {
      props: {
        messages: [
          {
            role: 'ai' as const,
            content: '整批文件已经读完，请选择下一步。',
            time: '13:54',
            decisionOptions: [
              {
                id: 'recommended',
                label: '按 AI 建议处理',
                description: '归档模板并同步可安全执行的业务数据',
                message: '按建议处理',
                recommended: true,
              },
              {
                id: 'template-only',
                label: '仅归档模板库',
                description: '不写业务数据库',
                message: '全部只归档到模板库',
              },
              {
                id: 'custom',
                label: '自定义处理方式',
                description: '继续和 AI 商量',
                composePrefill: '我想这样处理：',
              },
            ],
          },
        ],
        isLoading: false,
        isStreamingReply: false,
        loadingProgressText: '',
        messageHeights: new Map<number, number>(),
        latestAiMessageIndex: 0,
        playingMsgIdx: -1,
        isMessageCollapsed: () => false,
        getCollapsedPreview: () => '',
        canSpeakMessage: () => false,
        decisionOptionsEnabled: true,
      },
    })

    const buttons = wrapper.findAll('.decision-option')
    expect(buttons).toHaveLength(3)
    expect(buttons.map((button) => button.text())).toEqual([
      expect.stringContaining('按 AI 建议处理'),
      expect.stringContaining('仅归档模板库'),
      expect.stringContaining('自定义处理方式'),
    ])
    expect(buttons[0].classes()).toContain('is-recommended')
    await buttons[1].trigger('click')
    expect(wrapper.emitted('decision-option')?.[0]).toEqual([
      expect.objectContaining({ id: 'template-only', message: '全部只归档到模板库' }),
      0,
    ])
  })

  it('keeps resolved historical decision options visible but disabled', () => {
    const wrapper = mount(ChatMessageList, {
      props: {
        messages: [
          {
            role: 'ai' as const,
            content: '请选择下一步。',
            time: '13:54',
            decisionOptions: [{ id: 'recommended', label: '按 AI 建议处理', message: '按建议处理' }],
          },
        ],
        isLoading: false,
        isStreamingReply: false,
        loadingProgressText: '',
        messageHeights: new Map<number, number>(),
        latestAiMessageIndex: 0,
        playingMsgIdx: -1,
        isMessageCollapsed: () => false,
        getCollapsedPreview: () => '',
        canSpeakMessage: () => false,
        decisionOptionsEnabled: false,
      },
    })

    expect(wrapper.get('.decision-option').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.decision-options__resolved').text()).toContain('这组选择已结束')
  })

  it('renders a structured Business Harness trace and condenses planner narration', () => {
    const wrapper = mount(ChatMessageList, {
      props: {
        messages: [
          {
            role: 'ai' as const,
            content: '我已根据语义生成动态工作流计划：\n工具探测概览：business_db.write\n需要审批后执行。',
            time: '11:39',
            agentRunTrace: {
              run_id: 'run_business_1',
              intent: 'business_db_write',
              status: 'waiting' as const,
              terminal: false,
              phases: [
                {
                  kind: 'tool' as const,
                  status: 'waiting' as const,
                  started_event_id: 'event_1',
                  title: '工具调用',
                  node_id: 'write_business_product',
                  tool_id: 'business_db',
                  action: 'write',
                  observations: [],
                  waiting_approval: true,
                  retries: 0,
                  repair_history: [],
                },
              ],
            },
          },
        ],
        isLoading: false,
        isStreamingReply: false,
        loadingProgressText: '',
        messageHeights: new Map<number, number>(),
        latestAiMessageIndex: 0,
        playingMsgIdx: -1,
        isMessageCollapsed: () => false,
        getCollapsedPreview: () => '',
        canSpeakMessage: () => false,
      },
    })

    expect(wrapper.get('[data-testid="agent-run-trace"]').text()).toContain('业务数据写入')
    expect(wrapper.get('[data-testid="agent-run-trace"] .fa-database').exists()).toBe(true)
    expect(wrapper.get('.message-orchestration-intro').text()).toContain('展开卡片')
    expect(wrapper.find('.message-html').exists()).toBe(false)
  })

  it('projects a legacy approval card into the same visual orchestration trace', () => {
    const wrapper = mount(ChatMessageList, {
      props: {
        messages: [
          {
            role: 'ai' as const,
            content: '我已根据语义生成动态工作流计划：\n工作编排：写入客户\n以下操作需要审批后执行：business_db.write',
            time: '11:57',
            todoSteps: ['识别业务实体与写入字段', '通过受控业务服务写入数据库', '返回写入结果'],
            approvalCard: {
              plan_id: 'plan_legacy_1',
              intent: 'business_db_write',
              status: 'pending' as const,
              blocking_nodes: ['write_business_customer'],
              reason: 'plan requires human risk approval',
              todo: ['识别业务实体与写入字段', '通过受控业务服务写入数据库', '返回写入结果'],
            },
          },
        ],
        isLoading: false,
        isStreamingReply: false,
        loadingProgressText: '',
        messageHeights: new Map<number, number>(),
        latestAiMessageIndex: 0,
        playingMsgIdx: -1,
        isMessageCollapsed: () => false,
        getCollapsedPreview: () => '',
        canSpeakMessage: () => false,
      },
    })

    const trace = wrapper.get('[data-testid="agent-run-trace"]')
    expect(trace.text()).toContain('业务数据写入')
    expect(trace.text()).toContain('业务数据库')
    expect(trace.find('.fa-database').exists()).toBe(true)
    expect(wrapper.find('.todo-panel').exists()).toBe(false)
    expect(wrapper.find('.message-html').exists()).toBe(false)
    expect(wrapper.get('[data-testid="chat-approval-inline-card"]').exists()).toBe(true)
  })

  it('restores collapsed previews for earlier assistant messages', async () => {
    const wrapper = mount(ChatMessageList, {
      props: {
        messages: [
          { role: 'ai' as const, content: '较早的长回复', time: '11:38' },
          { role: 'ai' as const, content: '最新回复', time: '11:39' },
        ],
        isLoading: false,
        isStreamingReply: false,
        loadingProgressText: '',
        messageHeights: new Map([[0, 400]]),
        latestAiMessageIndex: 1,
        playingMsgIdx: -1,
        isMessageCollapsed: (_message, index) => index === 0,
        getCollapsedPreview: () => '较早的长回复…',
        canSpeakMessage: () => false,
      },
    })

    expect(wrapper.get('.msg-fold__text').text()).toContain('较早的长回复')
    expect(wrapper.findAll('.message')[0].attributes('style')).toContain('min-height: auto')
    await wrapper.get('.msg-fold__action').trigger('click')
    expect(wrapper.emitted('expand-message')).toEqual([[0]])
  })
})

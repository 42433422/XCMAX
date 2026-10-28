import { describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { afterEach } from 'vitest'
enableAutoUnmount(afterEach)
import ChatMessageList from './ChatMessageList.vue'

const defaultProps = {
  isLoading: false, isStreamingReply: false, loadingProgressText: '',
  messageHeights: new Map<number, number>(), latestAiMessageIndex: 0, playingMsgIdx: -1,
  isMessageCollapsed: () => false, getCollapsedPreview: () => '', canSpeakMessage: () => false,
}
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
        ...defaultProps,
      },
    })

    expect(wrapper.get('[data-testid="agent-run-trace"]').text()).toContain('业务数据写入')
    expect(wrapper.get('[data-testid="agent-run-trace"] .fa-database').exists()).toBe(true)
    expect(wrapper.get('.message-orchestration-intro').text()).toContain('展开卡片')
    expect(wrapper.find('.message-html').exists()).toBe(false)
  })

  it('keeps an in-chat confirm entry for a run waiting on a later step (#2289)', async () => {
    const trace = { run_id: 'run_wait_2', intent: 'stock_out', status: 'waiting' as const, terminal: false, phases: [] }
    const wrapper = mount(ChatMessageList, {
      props: {
        messages: [{ role: 'ai' as const, content: '等待确认', time: '12:00', agentRunTrace: trace }],
        ...defaultProps,
      },
    })
    await wrapper.get('[data-testid="chat-run-approve"]').trigger('click')
    expect(wrapper.emitted('approve-run')).toEqual([['run_wait_2']])
    await wrapper.setProps({ messages: [{ role: 'ai' as const, content: '完成', time: '12:01', agentRunTrace: { ...trace, status: 'success' as const, terminal: true } }] })
    expect(wrapper.find('[data-testid="chat-run-approve"]').exists()).toBe(false)
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
        ...defaultProps,
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


it('renders execution progress, safe user text, diagnostic errors and forwards message actions', async () => {
  const host = ref<HTMLElement | null>(null)
  const message = { role: 'ai' as const, content: '已导出', time: '12:00', streamingShell: true,
    shipmentDownloadUrl: '/export.xlsx', todoSteps: ['检查库存'],
    executionProgress: ['success', 'failed', 'cancelled', 'waiting', 'retrying', 'running'].map((status, at) => ({ status, at, label: `步骤${at}` })),
    nodeResults: [{ node_id: 'node', tool_id: 'export', action: 'write', success: false,
      retries: 2, duration_ms: 150, error: '暂时不可用', recovery_hint: '重新导出' }],
  }
  const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: [message,
    { role: 'user', content: '<b>谢谢</b><script>bad()</script>', time: '12:01' }], latestAiMessageIndex: 2,
    chatMessagesRef: host, showDiagnosticMetadata: true, canSpeakMessage: () => true, playingMsgIdx: 0,
    messageHeights: new Map([[0, 200]]), isLoading: true, loadingProgressText: '正在导出' } })
  await wrapper.vm.$nextTick()
  expect(host.value).toBe(wrapper.get('#chatMessages').element)
  expect(wrapper.findAll('.execution-timeline__marker').map(x => x.text())).toEqual(['✓', '×', '■', 'Ⅱ', '↻', '●'])
  expect(wrapper.get('.execution-timeline__current').text()).toBe('步骤5')
  expect(wrapper.get('.execution-timeline').attributes('open')).toBeUndefined()
  expect(wrapper.get('.todo-panel').text()).toContain('检查库存')
  expect(wrapper.get('.trace-node-meta').text()).toContain('重试 2 次 · 150ms')
  expect(wrapper.get('.trace-node-error').text()).toContain('暂时不可用')
  expect(wrapper.get('.trace-node-hint').text()).toContain('重新导出')
  expect(wrapper.find('script').exists()).toBe(false)
  expect(wrapper.findAll('.message')[0].attributes('style')).toContain('min-height: 200px')
  expect(wrapper.get('.chat-loading-row').text()).toContain('正在导出')
  wrapper.get('.message-shipment-actions a').element.addEventListener('click', event => event.preventDefault())
  await wrapper.get('.message-shipment-actions a').trigger('click')
  await wrapper.get('.message-tts-btn').trigger('click')
  await wrapper.get('.msg-fold__action--collapse').trigger('click')
  expect(wrapper.emitted('shipment-download-click')).toEqual([[]])
  expect(wrapper.emitted('toggle-message-tts')).toEqual([[0, '已导出']])
  expect(wrapper.emitted('collapse-message')).toEqual([[0]])
  await wrapper.setProps({ playingMsgIdx: -1, isStreamingReply: true, messages: [{ ...message, streamingShell: false, toolProgressLabel: '自定义步骤' }] })
  expect(wrapper.get('.message-tts-btn .fa-volume-up').exists()).toBe(true)
  expect(wrapper.get('.execution-timeline__current').text()).toBe('自定义步骤')
  expect(wrapper.find('.chat-loading-row').exists()).toBe(false)
})

 it.each([true, false])('copies only rendered body and reports clipboard success=%s', async success => {
  const writeText = success ? vi.fn().mockResolvedValue(undefined) : vi.fn().mockRejectedValue(new Error('denied'))
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  const wrapper = mountList(true)
  await wrapper.get('.message-copy-btn').trigger('click')
  await Promise.resolve()
  expect(writeText).toHaveBeenCalledWith('系统显示 "正常"。')
  expect(wrapper.get('.message-copy-btn').attributes('aria-label')).toBe(success ? '已复制' : '复制失败，请重试')
  expect(wrapper.get('.message-copy-btn .fa-copy').exists()).toBe(true)
 })

it.each([true, false])('uses the native desktop clipboard and reports accepted=%s', async success => {
  const write = vi.fn().mockResolvedValue({ ok: success })
  const webWrite = vi.fn()
  Object.defineProperty(window, 'xcagiDesktop', { configurable: true, value: { clipboardWriteText: write } })
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: webWrite } })
  const wrapper = mountList()
  await wrapper.get('.message-copy-btn').trigger('click')
  await Promise.resolve()
  expect(write).toHaveBeenCalledWith('系统显示 "正常"。')
  expect(webWrite).not.toHaveBeenCalled()
  expect(wrapper.get('.message-copy-btn').attributes('aria-label')).toBe(success ? '已复制' : '复制失败，请重试')
  Reflect.deleteProperty(window, 'xcagiDesktop')
})

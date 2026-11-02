import { describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { afterEach } from 'vitest'
enableAutoUnmount(afterEach)
import ChatMessageList from './ChatMessageList.vue'
import AgentRunTrace from './AgentRunTrace.vue'
import { proactiveReplyMessageId } from '@/composables/useProactiveReplySuggestions'

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
  it('keeps completed suggestions visible at the bottom without moving someone reading earlier messages', async () => {
    const messages = [{ role: 'ai' as const, content: '第一条回复', time: '12:00' },
      { role: 'ai' as const, content: '第二条回复', time: '12:01' }]
    const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages, sessionKey: 'scope' } })
    const host = wrapper.get('#chatMessages').element as HTMLElement
    Object.defineProperties(host, { scrollHeight: { configurable: true, writable: true, value: 5000 }, clientHeight: { configurable: true, value: 500 } })
    const choice = (message: typeof messages[number]) => ({ id: 'choice', text: '继续说明', scopeKey: 'scope', messageId: proactiveReplyMessageId(message) })
    const first = choice(messages[0]!), second = choice(messages[1]!)
    await wrapper.setProps({ proactiveSuggestions: new Map([[second.messageId, [second]]]) })
    expect(host.scrollTop).toBe(5000)
    host.scrollTop = 120
    await wrapper.get('#chatMessages').trigger('scroll')
    Object.defineProperty(host, 'scrollHeight', { value: 6000 })
    await wrapper.setProps({ proactiveSuggestions: new Map([[first.messageId, [first]], [second.messageId, [second]]]) })
    expect(host.scrollTop).toBe(120)
  })

  it('shows server and cache failures separately and retries only the same saved-message identity', async () => {
    const message = { role: 'user' as const, content: '记录', time: '12:00', persistence: {
      id: 'message-a', status: 'failed' as const, localSaved: false, error: '消息保存未确认。不会重新执行任务。',
      request: { role: 'user' as const, content: '记录' },
    } }
    const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: [message] } })
    expect(wrapper.get('.message-save-status').text()).toContain('本机副本保存失败')
    expect(wrapper.get('.message-save-error').text()).toContain('不会重新执行任务')
    await wrapper.findAll('button').find(button => button.text() === '仅重试保存')!.trigger('click')
    expect(wrapper.emitted('retry-save')).toEqual([['message-a']])
    await wrapper.setProps({ messages: [{ ...message, persistence: { ...message.persistence, status: 'saving', error: '' } }] })
    expect(wrapper.text()).toContain('正在保存')
    expect(wrapper.text()).not.toContain('仅重试保存')
    await wrapper.setProps({ messages: [{ ...message, persistence: { id: 'message-a', status: 'saved', localSaved: true } }] })
    expect(wrapper.find('.message-save-status').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('保存失败')
  })

  it('omits ordinary persistence diagnostics and preserves true failures inline', () => {
    const messages = ['local', 'saved'].map((status, i) => ({ role: 'user' as const, content: '记录', time: '12:00', persistence: { id: String(i), status: status as 'local' | 'saved' } }))
    const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages } })
    expect(wrapper.find('.message-save-status').exists()).toBe(false)
    expect(wrapper.find('.message-storage-details').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('保存详情')
    expect(wrapper.text()).not.toContain('服务端未核实')
  })

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
    wrapper.getComponent(AgentRunTrace).vm.$emit('auto-approve-tool', 'business_db')
    expect(wrapper.emitted('approve-run')).toEqual([['run_wait_2'], ['run_wait_2']])
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
 })


it.each([true, false])('uses the native bridge for collapsed=%s and excludes hidden content', async collapsed => {
  const nativeWrite = vi.fn().mockResolvedValue({ ok: true })
  Object.defineProperty(window, 'xcagiDesktop', { configurable: true, value: { clipboardWriteText: nativeWrite } })
  const wrapper = mount(ChatMessageList, { props: { ...defaultProps, isMessageCollapsed: () => collapsed, messages: [
    { role: 'user', time: '', content: '<p>第一段</p><p hidden>秘密</p><p>第二段<br>下一行</p>' },
    { role: 'ai', time: '', content: '清单：\n- 第一项\n- 第二项\n\n```js\nlet a = 1;\nlet b = 2;\n```' },
  ] } })
  await wrapper.findAll('.message-copy-btn')[0].trigger('click'); await Promise.resolve()
  expect(nativeWrite).toHaveBeenNthCalledWith(1, '第一段\n第二段\n下一行')
  await wrapper.findAll('.message-copy-btn')[1].trigger('click'); await Promise.resolve()
  const copied = nativeWrite.mock.calls[1][0] as string
  expect(copied).toContain('第一项\n第二项'); expect(copied).toContain('let a = 1;\nlet b = 2;')
  expect(copied).not.toContain('复制'); expect(copied).not.toContain('js')
  nativeWrite.mockResolvedValueOnce({ ok: false })
  await wrapper.findAll('.message-copy-btn')[0].trigger('click'); await Promise.resolve()
  expect(wrapper.findAll('.message-copy-btn')[0].attributes('aria-label')).toBe('复制失败，请重试')
  delete window.xcagiDesktop
})

it.each([true, false])('copies visible content safely when collapsed=%s', async collapsed => {
  const css = document.createElement('style')
  css.textContent = '.private-copy-test { display:none } .masked-copy-test { visibility:hidden } .concealed-copy-test { content-visibility:hidden }'
  document.head.append(css)
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  const wrapper = mount(ChatMessageList, { attachTo: document.body, props: { ...defaultProps, isMessageCollapsed: () => collapsed, messages: [{
    role: 'user', time: '', content: '<script>secret</script><p>公开</p><p class="private-copy-test">机密</p><div class="masked-copy-test"><span>继承机密</span></div><div class="concealed-copy-test">渲染隐藏机密</div><p>第二段</p>',
  }] } })
  await wrapper.get('.message-copy-btn').trigger('click'); await Promise.resolve()
  expect(writeText).toHaveBeenCalledWith('公开\n第二段')
  wrapper.unmount(); css.remove()
})

it('copies the condensed visible summary when a plan is collapsed', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  const wrapper = mount(ChatMessageList, { attachTo: document.body, props: { ...defaultProps, isMessageCollapsed: () => true, messages: [{
    role: 'ai', time: '', content: '动态工作流计划：内部明细', agentRunTrace: { run_id: '1', intent: '', status: 'running', phases: [], terminal: false },
  }] } })
  await wrapper.get('.message-copy-btn').trigger('click'); await Promise.resolve()
  expect(writeText).toHaveBeenCalledWith('执行计划已整理为任务编排，展开卡片可查看工具、步骤和运行详情。')
  wrapper.unmount()
})


it('offers failure recovery with visible original text without sending a request or showing continuation suggestions', async () => {
  const messages = [
    { role: 'user' as const, content: '仅回答测试', time: '12:00', turnId: 'turn-a' },
    { role: 'ai' as const, content: '处理失败：模型未返回正文', time: '12:00', turnId: 'turn-a', workflowAction: 'failed' },
  ]
  const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages } })
  expect(wrapper.get('[data-testid="chat-error-recovery"]').text()).toContain('仅回答测试')
  expect(wrapper.find('[data-testid="proactive-suggestions"]').exists()).toBe(false)
  await wrapper.findAll('button').find(button => button.text().includes('填入原文'))!.trigger('click')
  expect(wrapper.emitted('fill-example')).toEqual([['仅回答测试']])
  expect(wrapper.text()).not.toContain('查看模型状态')
})

it('shows an empty conversation example that only fills the composer', async () => {
  const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: [], emptyIntro: '当前工作区用于考勤查询。' } })
  expect(wrapper.text()).toContain('当前工作区用于考勤查询')
  expect(wrapper.text()).toContain('可用能力以当前配置为准')
  await wrapper.get('.chat-welcome button').trigger('click')
  expect(wrapper.emitted('fill-example')).toEqual([['请用一句话介绍你能做什么。仅回答，不执行操作。']])
})

it('retries only the exact user turn and does not substitute a later unbound message', async () => {
  const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: [
    { role: 'user', content: '本轮原文', time: '12:00', turnId: 'turn-a' },
    { role: 'user', content: '另一个未绑定输入', time: '12:01' },
    { role: 'ai', content: '处理失败：请重试', time: '12:02', turnId: 'turn-a' },
  ] } })
  await wrapper.findAll('button').find(button => button.text().includes('填入原文'))!.trigger('click')
  expect(wrapper.emitted('fill-example')).toEqual([['本轮原文']])
  await wrapper.setProps({ messages: [
    { role: 'user', content: '未绑定输入', time: '12:00' },
    { role: 'ai', content: '处理失败：请重试', time: '12:02', turnId: 'turn-b' },
  ] })
  expect(wrapper.findAll('button').some(button => button.text().includes('填入原文'))).toBe(false)
})

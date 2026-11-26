import { describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import { afterEach } from 'vitest'
enableAutoUnmount(afterEach)
import ChatMessageList from './ChatMessageList.vue'
import AgentRunTrace from './AgentRunTrace.vue'
import { proactiveReplyMessageId } from '@/composables/useProactiveReplySuggestions'
import type { ChatMessage } from '@/composables/useChatMessages'
import type { AgentStepView } from '@/utils/agentStepChain'

const defaultProps = {
  isLoading: false, isStreamingReply: false, loadingProgressText: '',
  messageHeights: new Map<number, number>(), latestAiMessageIndex: 0, playingMsgIdx: -1,
  isMessageCollapsed: () => false, canSpeakMessage: () => false,
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
      canSpeakMessage: () => false,
      showDiagnosticMetadata,
    },
  })
}

function runningStep(overrides: Partial<AgentStepView> = {}): AgentStepView {
  return {
    id: 'node-a', toolId: 'elt_import', action: 'execute', title: '导入明细 A', subtitle: '执行',
    state: 'running', retries: 0, live: false, ...overrides,
  }
}

describe('ChatMessageList', () => {
  it('keeps distinct legacy rows mounted while streaming changes their length', async () => {
    const messages = ref([
      { role: 'ai' as const, content: 'first', time: '12:00', turnId: 'same-turn' },
      { role: 'ai' as const, content: 'other', time: '12:00', turnId: 'same-turn' },
    ])
    const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: messages.value } })
    const first = wrapper.get('[data-message-index="0"]').element
    const second = wrapper.get('[data-message-index="1"]').element
    messages.value[0].content += ' streamed text'
    await nextTick()
    expect(wrapper.get('[data-message-index="0"]').element).toBe(first)
    expect(wrapper.get('[data-message-index="1"]').element).toBe(second)
    expect(first).not.toBe(second)
  })

  it('shows the pending turn under its own user message until the streaming reply takes over', async () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: '你好', time: '12:00', turnId: 'previous' },
      { role: 'ai', content: '你好！', time: '12:00', turnId: 'previous' },
      { role: 'user', content: '北京两日游', time: '12:01', turnId: 'current' },
    ]
    const wrapper = mount(ChatMessageList, { props: {
      ...defaultProps, messages, isLoading: true, pendingTurnId: 'current',
    } })
    expect(wrapper.get('[data-message-index="2"] [data-testid="chat-turn-pending"]').text()).toContain('正在生成')
    expect(wrapper.findAll('[data-testid="chat-turn-pending"]')).toHaveLength(1)
    expect(wrapper.find('.chat-loading-row').exists()).toBe(false)

    await wrapper.setProps({ messages: [...messages, {
      role: 'ai', content: '', time: '12:01', turnId: 'current', streamingShell: true, streamStatus: 'submitted',
    }], isStreamingReply: true })
    expect(wrapper.find('[data-testid="chat-turn-pending"]').exists()).toBe(false)
    expect(wrapper.findAll('.chat-typing-indicator')).toHaveLength(1)
  })

  it('shows a stop notice inside the stopped turn, not below a newer answer', async () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: '旧问题', time: '12:00', turnId: 'old' },
      { role: 'ai', content: '已接收的部分正文', time: '12:00', turnId: 'old' },
    ]
    const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages, stoppedTurnId: 'old' } })
    expect(wrapper.get('[data-message-index="1"] [data-testid="chat-turn-stopped"]').text()).toContain('已停止接收本轮回复')
    expect(wrapper.findAll('[role="listitem"]')).toHaveLength(2)

    await wrapper.setProps({ messages: [...messages, {
      role: 'user', content: '新问题', time: '12:01', turnId: 'new',
    }, {
      role: 'ai', content: '新答复', time: '12:02', turnId: 'new',
    }] })
    expect(wrapper.find('[data-testid="chat-turn-stopped"]').exists()).toBe(false)
    expect(wrapper.get('[data-message-index="3"]').text()).toContain('新答复')
  })

  it('keeps the activity indicator and receipt running after visible text removes the streaming shell', async () => {
    const messages = ref<ChatMessage[]>([{
      role: 'ai', content: '已开始读取附件。', time: '12:00', streamingShell: false, streamStatus: 'streaming',
      executionProgress: [{ phase: 'read', label: '正在读取附件', status: 'running', at: '12:00' }],
    }])
    const wrapper = mount(ChatMessageList, {
      props: { ...defaultProps, messages: messages.value, isLoading: true, isStreamingReply: true },
    })
    expect(wrapper.get('.message-html').text()).toContain('已开始读取附件')
    expect(wrapper.get('.chat-typing-indicator').text()).toContain('正在读取附件')
    expect(wrapper.find('[data-testid="agent-step-chain"]').exists()).toBe(false)
    expect(wrapper.get('.message-receipt__status').text()).toBe('进行中')

    messages.value[0].content += '正在写入。'
    await nextTick()
    expect(wrapper.find('.chat-typing-indicator').exists()).toBe(true)
    expect(wrapper.get('.message-receipt__status').text()).toBe('进行中')
    messages.value[0].streamStatus = 'ready'
    messages.value[0].executionProgress![0].status = 'success'
    messages.value[0].workflowAction = 'completed'
    await nextTick()
    expect(wrapper.find('.chat-typing-indicator').exists()).toBe(false)
    expect(wrapper.get('.message-receipt__status').text()).toBe('已完成')
  })

  it.each([
    ['waiting_auth', '等待授权'],
    ['waiting_approval', '待确认'],
    ['waiting_input', '待核对'],
    ['future_wait_state', '待核对'],
    ['', '待核对'],
    ['completed', '已完成'],
    ['succeeded', '已完成'],
    ['failed', '失败'],
    ['cancelled', '已取消'],
    ['interrupted', '已中断'],
    ['rejected', '未批准'],
    ['not_started', '未开始'],
    ['queued', '进行中'],
    ['running', '进行中'],
  ])('renders %s from its receipt instead of defaulting to completion', (workflowAction, label) => {
    const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: [{
      role: 'ai', content: '原任务状态', time: '12:00', streamStatus: 'ready', workflowAction,
      toolProgressLabel: '查看原任务状态',
    }] } })
    expect(wrapper.get('.message-receipt__status').text()).toBe(label)
    expect(wrapper.find('[data-testid="chat-run-approve"]').exists()).toBe(false)
  })

  it.each([false, true])('keeps authorization distinct from approval and lets unknown receipts take precedence (%s)', unknown => {
    const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: [{
      role: 'ai', content: '原任务等待授权。', time: '12:00', streamStatus: 'ready', workflowAction: 'waiting_auth',
      executionProgress: [{ phase: 'read', label: '查看原任务状态', status: 'waiting', at: '12:00' }],
      liveSteps: [runningStep()],
      ...(unknown ? { execution: { idempotencyKey: 'original', intent: 'read', committed: false, effect: 'unknown', outcome: 'unknown' } } : {}),
    }] } })
    expect(wrapper.get('.message-receipt__status').text()).toBe(unknown ? '待核对' : '等待授权')
    expect(wrapper.text()).not.toContain('已完成')
    expect(wrapper.find('[data-testid="chat-run-approve"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="chat-retry-model"]').exists()).toBe(false)
  })

  it('keeps attachments and planning in one execution chain without a synthetic tool step', async () => {
    const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: [{
      role: 'ai', content: '', time: '12:00', streamStatus: 'streaming',
      toolProgressLabel: '正在处理任务…', thinkingSteps: '生成计划…',
      trace: [{ tool: 'list_attachments', ok: true, ms: 0 }],
      agentRunTrace: {
        run_id: 'run-plan', intent: '', status: 'running', terminal: false,
        phases: [{ kind: 'planner', started_event_id: 'plan', status: 'running', title: '正在生成执行计划' }],
      },
    }] } })
    const chain = wrapper.get('[data-testid="chat-task-trace"]')
    expect(chain.get('.chat-typing-indicator').text()).toContain('正在生成执行计划')
    expect(chain.find('[data-testid="chat-turn-trace"]').exists()).toBe(true)
    expect(chain.find('[data-testid="agent-run-trace"]').exists()).toBe(true)
    expect(chain.find('[data-testid="agent-step-chain"]').exists()).toBe(false)
    expect(chain.find('.message-task-trace__activity').exists()).toBe(false)
    expect(chain.text()).not.toContain('1 步')
  })

  it('updates the first parallel node without waiting for the last node or replacing the message', async () => {
    const messages = ref<ChatMessage[]>([{
      role: 'ai', content: '正在并行导入两份附件。', time: '12:00', streamStatus: 'streaming',
      toolProgressLabel: '正在并行导入两份附件', thinkingSteps: '旧的过程说明',
      nodeResults: [{ node_id: 'preview', tool_id: 'elt_import', action: 'preview', success: true }],
      agentRunTrace: { run_id: 'run-a', intent: 'import', status: 'success', terminal: true, phases: [] },
      liveSteps: [
        runningStep({ hint: 'A 已处理 20 行', progress: 10, processedRows: 20, totalRows: 200 }),
        runningStep({ id: 'node-b', title: '导入明细 B', hint: 'B 已处理 60 行', progress: 60, processedRows: 60, totalRows: 100 }),
      ],
    }])
    const wrapper = mount(ChatMessageList, {
      props: { ...defaultProps, messages: messages.value, isLoading: true, isStreamingReply: true },
    })
    const messageElement = wrapper.get('[data-message-index="0"]').element
    expect(wrapper.find('[data-testid="agent-run-trace"]').exists()).toBe(false)
    expect(wrapper.find('.message-task-trace__activity').exists()).toBe(false)
    expect(wrapper.find('.message-receipt').exists()).toBe(false)
    expect(wrapper.findAll('.asc-step')).toHaveLength(2)
    expect(wrapper.findAll('.asc-step')[0].get('progress').attributes('value')).toBe('10')
    expect(wrapper.findAll('.asc-step')[1].get('progress').attributes('value')).toBe('60')

    Object.assign(messages.value[0].liveSteps![0], { hint: 'A 已处理 100 行', progress: 50, processedRows: 100 })
    await nextTick()
    const rows = wrapper.findAll('.asc-step')
    expect(wrapper.get('[data-message-index="0"]').element).toBe(messageElement)
    expect(rows[0].get('.asc-live-hint').text()).toBe('A 已处理 100 行')
    expect(rows[0].get('progress').attributes('value')).toBe('50')
    expect(rows[0].text()).toContain('已处理 100 / 200 行')
    expect(rows[1].get('.asc-live-hint').text()).toBe('B 已处理 60 行')
    expect(rows[1].get('progress').attributes('value')).toBe('60')
    expect(rows[1].text()).toContain('已处理 60 / 100 行')
  })

  it.each([false, true])('shows missing tool receipts as needing reconciliation and removes active spinners (legacy trace=%s)', async withLegacyTrace => {
    const messages = ref<ChatMessage[]>([{
      role: 'ai', content: '已开始导入。', time: '12:00', streamStatus: 'streaming',
      liveSteps: [runningStep({ hint: '等待写入结果', progress: 50 })],
      executionProgress: [{ phase: 'import', label: '等待写入结果', status: 'running', at: '12:00' }],
      agentRunTrace: withLegacyTrace ? {
        run_id: 'run-a', intent: 'import', status: 'running', terminal: false,
        phases: [{
          kind: 'tool', status: 'running', started_event_id: 'phase-a', title: '导入',
          node_id: 'node-a', tool_id: 'elt_import', action: 'execute',
          observations: [], waiting_approval: false, retries: 0, repair_history: [],
        }],
      } : undefined,
    }])
    const wrapper = mount(ChatMessageList, {
      props: { ...defaultProps, messages: messages.value, isLoading: true, isStreamingReply: true },
    })
    expect(wrapper.find('.fa-spin').exists()).toBe(true)
    messages.value[0].streamStatus = 'ready'
    await wrapper.setProps({ isLoading: false, isStreamingReply: false })
    expect(wrapper.find('.chat-typing-indicator').exists()).toBe(false)
    expect(wrapper.find('.fa-spin').exists()).toBe(false)
    expect(wrapper.get('.asc-pill').text()).toBe('待核对')
    expect(wrapper.get('.asc-live-hint').text()).toBe('执行结果待核对')
    expect(wrapper.get('[data-testid="agent-step-chain"]').text()).not.toContain('待确认')
    expect(wrapper.get('.message-receipt__status').text()).toBe('待核对')
    // Display projection must not fabricate a terminal tool receipt or mutate SDK-derived state.
    expect(messages.value[0].liveSteps![0].state).toBe('running')
  })

  it('keeps a parallel node without a receipt visible when only another node has a final result', async () => {
    const messages = ref<ChatMessage[]>([{
      role: 'ai', content: '正在导入两个附件。', time: '12:00', streamStatus: 'streaming',
      liveSteps: [runningStep(), runningStep({ id: 'node-b', title: '导入明细 B' })],
    }])
    const wrapper = mount(ChatMessageList, {
      props: { ...defaultProps, messages: messages.value, isLoading: true, isStreamingReply: true },
    })
    messages.value[0].nodeResults = [{
      node_id: 'node-a', tool_id: 'elt_import', action: 'execute', success: true, output_preview: '附件 A 已写入',
    }]
    messages.value[0].streamStatus = 'ready'
    await wrapper.setProps({ isLoading: false, isStreamingReply: false })
    const rows = wrapper.findAll('.asc-step')
    expect(rows).toHaveLength(2)
    expect(rows[0].classes()).toContain('is-success')
    expect(rows[1].classes()).toContain('is-unknown')
    expect(rows[1].text()).toContain('导入明细 B')
    expect(rows[1].get('.asc-live-hint').text()).toBe('执行结果待核对')
    expect(wrapper.find('.fa-spin').exists()).toBe(false)
    expect(messages.value[0].liveSteps!.map(step => step.state)).toEqual(['running', 'running'])
  })

  it('retains explicit incomplete ELT receipts when the final workflow trace arrives', () => {
    const wrapper = mount(ChatMessageList, {
      props: { ...defaultProps, messages: [{
        role: 'ai', content: '运单已写入，客户及产品尚未提交写入。', time: '12:00', streamStatus: 'ready',
        turnId: 'elt-turn', workflowAction: 'failed',
        agentRunTrace: { run_id: 'elt-run', intent: 'import', status: 'failed', terminal: true, phases: [] },
        nodeResults: [{ node_id: 'node-a', tool_id: 'elt_import', action: 'execute', success: false }],
        liveSteps: [
          runningStep({ state: 'partial', output: '运单已写入' }),
          runningStep({ id: 'link', title: '客户及产品预演', state: 'deferred', output: '尚未提交写入' }),
        ],
      }] },
    })

    expect(wrapper.get('.asc-pill').text()).toBe('部分完成')
    expect(wrapper.get('.asc-step.is-deferred').text()).toContain('待处理')
    expect(wrapper.find('.asc-step.is-failed').exists()).toBe(false)
    expect(wrapper.find('.fa-spin').exists()).toBe(false)
    expect(wrapper.find('[data-testid="chat-error-recovery"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="chat-retry-model"]').exists()).toBe(false)
  })

  it('routes a blocked continuation to the original task without presenting it as a failure', async () => {
    const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: [{
      role: 'ai', content: '原导入任务待核对。', time: '12:00', turnId: 'original-turn',
      workflowAction: 'blocked', recoveryTaskId: 'original-task',
      toolProgressLabel: '请核对原任务回执',
    }] } })
    expect(wrapper.get('.message-receipt__status').text()).toBe('待核对')
    expect(wrapper.find('[data-testid="chat-error-recovery"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="chat-retry-model"]').exists()).toBe(false)
    await wrapper.get('[data-testid="chat-open-original-task"]').trigger('click')
    expect(wrapper.emitted('open-original-task')).toEqual([['original-task']])
  })

  it('renders a visible Business Harness result on the assistant message', () => {
    const wrapper = mount(ChatMessageList, {
      props: {
        ...defaultProps,
        messages: [
          {
            role: 'ai' as const,
            content: '客户已创建。',
            time: '12:00',
            businessResult: { status: 'completed', summary: '客户创建成功', facts: { customer_id: 23 } },
          },
        ],
      },
    })
    expect(wrapper.get('[data-testid="chat-business-result"]').text()).toContain('客户创建成功')
    expect(wrapper.get('[data-testid="chat-business-result"]').text()).toContain('客户 ID：23')
  })


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

  it('hides internal context counters by default but keeps legacy activity in the execution chain', async () => {
    const wrapper = mount(ChatMessageList, {
      props: {
        ...defaultProps,
        messages: [
          {
            role: 'ai' as const,
            content: '已清空知识库。',
            time: '17:00',
            thinkingSteps: '[正在调用工具:dataset_rag.clear_dataset]',
            agentRunTrace: { run_id: 'without-phases', intent: '', status: 'success', terminal: true, phases: [] },
          },
        ],
      },
    })
    expect(wrapper.find('.context-summary').exists()).toBe(false)
    const chain = wrapper.get('[data-testid="chat-task-trace"]')
    expect(chain.text()).not.toContain('dataset_rag.clear_dataset')
    await chain.get('.message-task-trace__trigger').trigger('click')
    expect(chain.text()).toContain('dataset_rag.clear_dataset')
    expect(wrapper.find('.trace-panel').exists()).toBe(false)
  })

  it('allows an explicit diagnostic surface to show context metadata', async () => {
    const wrapper = mountList(true)
    await wrapper.get('.message-receipt__summary').trigger('click')
    expect(wrapper.get('.context-summary').text()).toContain('已关联上下文')
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
    expect(wrapper.find('.message-orchestration-intro').exists()).toBe(false)
    expect(wrapper.find('.message-html').exists()).toBe(false)
  })

  it('keeps an in-chat confirm entry for a run waiting on a later step (#2289)', async () => {
    const trace = { run_id: 'run_wait_2', intent: 'stock_out', status: 'waiting' as const, terminal: false, phases: [] }
    const wrapper = mount(ChatMessageList, {
      props: {
        messages: [{ role: 'ai' as const, content: '等待确认', time: '12:00', streamStatus: 'ready', agentRunTrace: trace,
          liveSteps: [runningStep({ state: 'waiting' })] }],
        ...defaultProps,
      },
    })
    await wrapper.get('[data-testid="chat-run-approve"]').trigger('click')
    expect(wrapper.text()).not.toContain('待核对')
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
          { role: 'ai' as const, content: '较早的长回复'.repeat(30), time: '11:38' },
          { role: 'ai' as const, content: '最新回复', time: '11:39' },
        ],
        isLoading: false,
        isStreamingReply: false,
        loadingProgressText: '',
        messageHeights: new Map([[0, 400]]),
        latestAiMessageIndex: 1,
        playingMsgIdx: -1,
        isMessageCollapsed: (_message, index) => index === 0,
        canSpeakMessage: () => false,
      },
    })

    // 溢出检测在挂载后的下一个 tick 完成
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.msg-fold__inner').text()).toContain('较早的长回复')
    expect(wrapper.findAll('.message')[0].attributes('style')).toContain('min-height: auto')
    await wrapper.get('.msg-fold__trigger').trigger('click')
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
    canCollapseMessage: () => true,
    messageHeights: new Map([[0, 200]]), isLoading: true, loadingProgressText: '正在导出' } })
  await wrapper.vm.$nextTick()
  expect(host.value).toBe(wrapper.get('#chatMessages').element)
  const summary = wrapper.get('.message-receipt__summary')
  expect(summary.attributes('aria-expanded')).toBe('false')
  await summary.trigger('click')
  expect(wrapper.findAll('.execution-timeline__marker').map(x => x.text())).toEqual(['✓', '×', '■', 'Ⅱ', '↻', '●'])
  expect(wrapper.get('.execution-timeline__current').text()).toBe('步骤5')
  expect(wrapper.get('.todo-panel').text()).toContain('检查库存')
  expect(wrapper.get('.trace-node-meta').text()).toContain('重试 2 次 · 150ms')
  expect(wrapper.get('.trace-node-error').text()).toContain('暂时不可用')
  expect(wrapper.get('.trace-node-hint').text()).toContain('重新导出')
  expect(wrapper.find('script').exists()).toBe(false)
  expect(wrapper.findAll('.message')[0].attributes('style')).toContain('min-height: 200px')
  expect(wrapper.get('.chat-loading-row').text()).toContain('正在导出')
  expect(wrapper.find('.message-tts-btn').exists()).toBe(false)
  wrapper.get('.message-shipment-actions a').element.addEventListener('click', event => event.preventDefault())
  await wrapper.get('.message-shipment-actions a').trigger('click')
  await wrapper.setProps({ messages: [{ ...message, streamingShell: false }, ...wrapper.props('messages').slice(1)] })
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
  expect(writeText).not.toHaveBeenCalled()
  expect(wrapper.get('.message-copy-btn').attributes('aria-label')).toBe('没有可复制的正文')
  wrapper.unmount()
})


it('offers failure recovery in the message action row without repeating the original input', async () => {
  const messages = [
    { role: 'user' as const, content: '仅回答测试', time: '12:00', turnId: 'turn-a' },
    { role: 'ai' as const, content: '处理失败：模型未返回正文', time: '12:00', turnId: 'turn-a', workflowAction: 'failed' },
  ]
  const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages } })
  expect(wrapper.get('[data-testid="chat-error-recovery"]').text()).toContain('结果未知')
  expect(wrapper.get('[data-testid="chat-error-recovery"]').text()).not.toContain('仅回答测试')
  expect(wrapper.get('[data-testid="chat-error-recovery"]').text()).not.toContain('已执行的业务操作不会撤销')
  expect(wrapper.find('[data-testid="proactive-suggestions"]').exists()).toBe(false)
  await wrapper.get('[data-testid="chat-retry-model"]').trigger('click')
  expect(wrapper.emitted('retry-model')).toEqual([[{ text: '仅回答测试', turnId: 'turn-a' }]])
  await wrapper.get('[data-testid="chat-reconcile-turn"]').trigger('click')
  expect(wrapper.emitted('reconcile-turn')).toEqual([[1]])
  expect(wrapper.emitted('fill-example')).toBeUndefined()
  expect(wrapper.text()).not.toContain('查看模型状态')
})

it('asks for an explicit delete confirmation and does not offer it after a commit', async () => {
  const preview = mount(ChatMessageList, { props: { ...defaultProps, messages: [
    { role: 'user', content: '清理全部客户和产品', time: '12:00', turnId: 'turn-a' },
    { role: 'ai', content: '这是删除预览，尚未写入。', time: '12:00', turnId: 'turn-a', execution: {
      idempotencyKey: 'turn-a', intent: 'bulk_destructive', committed: false, effect: 'preview', confirmable: true, tenantId: 'demo', customerCount: 2, productCount: 3,
    } },
  ] } })
  await preview.get('[data-testid="chat-destructive-preview"] button').trigger('click')
  expect(preview.emitted('confirm-destructive')).toEqual([[{ text: '清理全部客户和产品', idempotencyKey: 'turn-a' }]])
  preview.unmount()

  const committed = mount(ChatMessageList, { props: { ...defaultProps, messages: [
    { role: 'user', content: '清理全部客户和产品', time: '12:00', turnId: 'turn-a' },
    { role: 'ai', content: '处理失败：模型未返回可显示的正文', time: '12:01', turnId: 'turn-a', execution: {
      idempotencyKey: 'turn-a', intent: 'bulk_destructive', committed: true, effect: 'committed', tenantId: 'demo', customerCount: 2, productCount: 3,
    } },
  ] } })
  expect(committed.get('[data-testid="chat-error-recovery"]').text()).toContain('已提交的业务操作不会再次执行')
  expect(committed.find('[data-testid="chat-destructive-preview"]').exists()).toBe(false)
  committed.unmount()
})

it('hides old unresolved confirmations and stale running receipts', () => {
  const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: [
    { role: 'user', content: '清理全部知识库数据库模版库', time: '12:00' },
    { role: 'ai', content: '范围尚未确定', time: '12:00', toolProgressLabel: '正在处理任务',
      executionProgress: [{ at: '12:00', label: '正在处理任务', status: 'running' }],
      execution: { idempotencyKey: 'old', intent: 'bulk_destructive', committed: false, effect: 'preview' },
    },
  ] } })
  expect(wrapper.find('[data-testid="chat-destructive-preview"]').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('正在处理任务')
  wrapper.unmount()
})

it('offers reconciliation only when the original write could have committed', async () => {
  const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: [
    { role: 'user', content: '导入这些附件', time: '12:00', turnId: 'import-turn' },
    { role: 'ai', content: '工具进程退出，请核对原任务', time: '12:01', turnId: 'import-turn', workflowAction: 'failed', execution: {
      idempotencyKey: 'import-turn', intent: 'elt_import', committed: false, effect: 'unknown', outcome: 'unknown',
    } },
  ] } })
  expect(wrapper.get('[data-testid="chat-error-recovery"]').text()).toContain('结果未知')
  expect(wrapper.find('[data-testid="chat-retry-model"]').exists()).toBe(false)
  await wrapper.get('[data-testid="chat-reconcile-turn"]').trigger('click')
  expect(wrapper.emitted('reconcile-turn')).toEqual([[1]])
})

it('keeps an empty conversation blank without welcome decorations', async () => {
  const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: [] } })
  expect(wrapper.find('.chat-welcome').exists()).toBe(false)
  expect(wrapper.text().trim()).toBe('')
})

it('retries only the exact user turn and does not substitute a later unbound message', async () => {
  const wrapper = mount(ChatMessageList, { props: { ...defaultProps, messages: [
    { role: 'user', content: '本轮原文', time: '12:00', turnId: 'turn-a' },
    { role: 'user', content: '另一个未绑定输入', time: '12:01' },
    { role: 'ai', content: '处理失败：请重试', time: '12:02', turnId: 'turn-a' },
  ] } })
  await wrapper.get('[data-testid="chat-retry-model"]').trigger('click')
  expect(wrapper.emitted('retry-model')).toEqual([[{ text: '本轮原文', turnId: 'turn-a' }]])
  await wrapper.setProps({ messages: [
    { role: 'user', content: '未绑定输入', time: '12:00' },
    { role: 'ai', content: '处理失败：请重试', time: '12:02', turnId: 'turn-b' },
  ] })
  expect(wrapper.find('[data-testid="chat-retry-model"]').exists()).toBe(false)
})

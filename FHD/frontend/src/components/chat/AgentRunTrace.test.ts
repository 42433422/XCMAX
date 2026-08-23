import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AgentRunTrace from './AgentRunTrace.vue'
import type { AgentRunTraceData } from '@/utils/agentRunTraceModel'
import { clearToolPermission, setToolPermission } from '@/utils/toolPermissionCache'

const mermaidRender = vi.fn(async () => ({ svg: '<svg data-testid="rendered-plan"></svg>' }))

vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: mermaidRender,
  },
}))

function makeTrace(status: AgentRunTraceData['status'] = 'waiting'): AgentRunTraceData {
  return {
    run_id: 'run_business_1234567890',
    intent: 'business_db_write',
    status,
    terminal: status === 'success' || status === 'failed',
    total_duration_ms: status === 'success' ? 1320 : undefined,
    last_event_id: 'event_2',
    phases: [
      {
        kind: 'planner',
        status: 'success',
        started_event_id: 'event_0',
        title: '执行计划已生成',
        step_count: 1,
      },
      {
        kind: 'tool',
        status,
        started_event_id: 'event_1',
        title: '工具调用',
        node_id: 'write_business_product',
        tool_id: 'business_db',
        action: 'write',
        params_json: '{\n  "entity": "products"\n}',
        output_preview: status === 'success' ? '产品已写入并完成回读验证' : undefined,
        observations: [],
        waiting_approval: status === 'waiting',
        retries: 0,
        repair_history: [],
      },
    ],
  }
}

describe('AgentRunTrace', () => {
  afterEach(() => {
    clearToolPermission('browser_search')
    mermaidRender.mockClear()
  })

  it('shows a collapsible Business Harness card with tool-specific icons', () => {
    const wrapper = mount(AgentRunTrace, { props: { trace: makeTrace() } })

    const card = wrapper.get('[data-testid="agent-run-trace"]')
    expect((card.element as HTMLDetailsElement).open).toBe(true)
    expect(card.text()).toContain('XCAGI Business Harness')
    expect(card.text()).toContain('业务数据写入')
    expect(card.text()).toContain('等待确认')
    expect(card.find('.fa-database').exists()).toBe(true)
    expect(card.find('.art-step.has-detail').exists()).toBe(true)
  })

  it('defaults successful traces to collapsed while retaining a compact summary', () => {
    const wrapper = mount(AgentRunTrace, { props: { trace: makeTrace('success') } })
    const card = wrapper.get('[data-testid="agent-run-trace"]')

    expect((card.element as HTMLDetailsElement).open).toBe(false)
    expect(card.get('.art-status-pill').text()).toContain('已完成')
    expect(card.get('.art-duration').text()).toBe('1.3s')
  })

  it('exposes nested tool input and output through a details row', () => {
    const wrapper = mount(AgentRunTrace, { props: { trace: makeTrace('success') } })
    const toolStep = wrapper.findAll('.art-step').find((node) => node.classes().includes('is-tool'))

    expect(toolStep).toBeTruthy()
    expect(toolStep!.text()).toContain('business_db.write')
    expect(toolStep!.text()).toContain('产品已写入并完成回读验证')
    expect(toolStep!.find('.art-step-chevron').exists()).toBe(true)
  })

  it('renders failure, retry, observation and remembered-permission details', async () => {
    setToolPermission('browser_search', 'persistent')
    const trace: AgentRunTraceData = {
      run_id: 'run_complex_failure_9876543210',
      intent: 'research_and_write_a_customer_record_with_a_long_title',
      status: 'failed',
      terminal: true,
      total_duration_ms: 61_000,
      last_event_id: 'event_failure',
      phases: [
        {
          kind: 'planner',
          status: 'failed',
          started_event_id: 'event_plan',
          title: '计划生成异常',
          detail: '缺少必要字段',
        },
        {
          kind: 'tool',
          status: 'waiting',
          started_event_id: 'event_tool',
          duration_ms: 500,
          title: '查询网页',
          node_id: 'lookup',
          tool_id: 'browser_search',
          action: 'query',
          params_json: '{"query":"XCAGI"}',
          error: '等待审批后重试',
          observations: ['发现一条候选结果'],
          waiting_approval: true,
          retries: 2,
          repair_history: ['已修复查询参数'],
        },
        {
          kind: 'tool',
          status: 'success',
          started_event_id: 'event_verify',
          title: '校验结果',
          node_id: 'verify',
          tool_id: 'terminal_exec',
          action: 'execute',
          observations: [],
          waiting_approval: false,
          retries: 0,
          repair_history: [],
        },
        {
          kind: 'run',
          status: 'failed',
          started_event_id: 'event_run',
          duration_ms: 12_000,
          title: '执行结束',
          subtitle: '需要人工处理',
          final_output_preview: '任务未写入业务数据',
        },
      ],
    }
    const wrapper = mount(AgentRunTrace, { props: { trace } })

    expect(wrapper.text()).toContain('research and write')
    expect(wrapper.text()).toContain('2 项异常')
    expect(wrapper.text()).toContain('重试 2')
    expect(wrapper.text()).toContain('已记住授权')
    expect(wrapper.text()).toContain('缺少必要字段')
    expect(wrapper.text()).toContain('发现一条候选结果')
    expect(wrapper.text()).toContain('已修复查询参数')
    expect(wrapper.text()).toContain('任务未写入业务数据')
    expect(wrapper.get('.art-duration').text()).toBe('1m 1s')
    expect(wrapper.get('.art-step-duration').text()).toBe('500ms')
    expect(wrapper.find('.fa-globe').exists()).toBe(true)
    expect(wrapper.find('.fa-terminal').exists()).toBe(true)

    await wrapper.get('.art-auto-approve').trigger('click')
    expect(wrapper.emitted('grant-tool-permission')).toEqual([['browser_search', 'session']])
    expect(wrapper.emitted('auto-approve-tool')).toEqual([['browser_search']])
  })

  it('lazily renders the execution graph when its disclosure opens', async () => {
    const trace = makeTrace('success')
    trace.phases.push({
      kind: 'tool',
      status: 'success',
      started_event_id: 'event_3',
      title: '发送通知',
      node_id: 'notify',
      tool_id: 'message_sender',
      action: 'send',
      output_preview: '通知已发送',
      observations: [],
      waiting_approval: false,
      retries: 0,
      repair_history: [],
    })
    const wrapper = mount(AgentRunTrace, { props: { trace } })
    const graph = wrapper.get('details.art-plan-graph')

    ;(graph.element as HTMLDetailsElement).open = true
    await graph.trigger('toggle')
    await flushPromises()

    expect(mermaidRender).toHaveBeenCalledOnce()
    expect(wrapper.get('.mermaid-host').html()).toContain('data-testid="rendered-plan"')
  })
})

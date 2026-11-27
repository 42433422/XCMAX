import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AgentRunTrace from './AgentRunTrace.vue'
import type { AgentRunTraceData } from '@/utils/agentRunTraceModel'
import { clearToolPermission, setToolPermission } from '@/utils/toolPermissionCache'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'

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
  it('shows failure details and diagnostic identity without losing a measured zero', () => {
    const trace: AgentRunTraceData = {
      run_id: 'run-failed', trace_id: 'trace-a', intent: '', status: 'failed', terminal: true, total_duration_ms: 0,
      phases: [{ kind: 'run', title: '执行失败', status: 'failed', started_event_id: 'failed',
        trace_id: 'trace-a', span_id: 'span-a', error_code: 'tool_timeout', detail: '等待工具回执超时', duration_ms: 0 }],
    }
    const wrapper = mount(AgentRunTrace, { props: { trace, showDiagnosticMetadata: true } })
    expect(wrapper.get('.art-duration').text()).toBe('0ms')
    expect(wrapper.text()).toContain('等待工具回执超时')
    expect(wrapper.text()).toContain('tool_timeout')
    expect(wrapper.text()).toContain('trace-a')
    expect(wrapper.text()).toContain('run-failed')
    expect(wrapper.text()).toContain('span-a')
  })

  it('keeps successful run identities out of the user-facing execution trace', () => {
    const trace = makeTrace('success')
    trace.trace_id = 'trace-hidden'
    trace.phases[0].trace_id = 'phase-hidden'
    const wrapper = mount(AgentRunTrace, { props: { trace } })
    expect(wrapper.text()).not.toContain('诊断信息')
    expect(wrapper.text()).not.toContain('trace-hidden')
    expect(wrapper.text()).not.toContain('phase-hidden')
    expect(wrapper.find('.art-step.is-planner.has-detail').exists()).toBe(false)
  })

  afterEach(() => {
    clearToolPermission('browser_search')
    setRuntimeTenantStorageScopeInput(null)
  })

  it('shows a collapsible Business Harness card with tool-specific icons', () => {
    const wrapper = mount(AgentRunTrace, { props: { trace: makeTrace() } })

    const card = wrapper.get('[data-testid="agent-run-trace"]')
    expect((card.element as HTMLDetailsElement).open).toBe(true)
    expect(card.text()).not.toContain('XCAGI Business Harness')
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
    setRuntimeTenantStorageScopeInput({ localUserId: 42 })
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
    expect(wrapper.text()).toContain('执行失败')
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


})

it.each([
  ['inventory', 'read', '业务资料', 'fa-database'], ['search', 'search', '搜索', 'fa-search'],
  ['spreadsheet', 'export', '表格', 'fa-table'], ['document', 'create', '文档', 'fa-file-text-o'],
  ['message', 'send', '消息', 'fa-envelope-o'], ['approval', 'approve', '审批中心', 'fa-check-square-o'],
  ['attachment', 'import', 'attachment', 'fa-upload'], ['custom_tool', 'custom_action', 'custom tool', 'fa-wrench'],
])('labels %s actions and keeps empty phase rows non-interactive', async (tool, action, label, icon) => {
  const trace = makeTrace('running'); trace.intent = ''; trace.run_id = 'run_short'
  Object.assign(trace.phases[1], { tool_id: tool, action, params_json: '', status: 'blocked' })
  const wrapper = mount(AgentRunTrace, { props: { trace } })
  expect(wrapper.get('.art-task-title').text()).toContain(label)
  expect(wrapper.find(`.${icon}`).exists()).toBe(true)
  expect(wrapper.find('.fa-ban').exists()).toBe(true)
  const summary = wrapper.get('.is-tool .art-step-summary')
  const event = new MouseEvent('click', { bubbles: true, cancelable: true })
  summary.element.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
  expect(summary.attributes('aria-disabled')).toBe('true')
  wrapper.unmount()
})

 it('preserves explicit disclosure choices across execution updates', async () => {
  const wrapper = mount(AgentRunTrace, { props: { trace: makeTrace('waiting') } })
  await wrapper.get('.art-summary').trigger('click')
  await wrapper.get('.art-step.is-tool > summary').trigger('click')
  await wrapper.setProps({ trace: makeTrace('success') })
  await wrapper.setProps({ trace: makeTrace('failed') })
  expect((wrapper.get('.art-trace').element as HTMLDetailsElement).open).toBe(false)
  expect((wrapper.get('.art-step.is-tool').element as HTMLDetailsElement).open).toBe(false)
  await wrapper.get('.art-summary').trigger('click')
  await wrapper.setProps({ trace: makeTrace('success') })
  expect((wrapper.get('.art-trace').element as HTMLDetailsElement).open).toBe(true)
 })

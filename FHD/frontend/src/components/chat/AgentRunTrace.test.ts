import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AgentRunTrace from './AgentRunTrace.vue'
import type { AgentRunTraceData } from '@/utils/agentRunTraceModel'

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
})

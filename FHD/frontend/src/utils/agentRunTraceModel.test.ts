import { describe, expect, it } from 'vitest'
import type { AgentRunEvent } from '@/api/agentRuns'
import {
  buildAgentRunTraceFromEvents,
  isTrivialChatTrace,
  shouldShowAgentRunPlanGraph,
} from './agentRunTraceModel'

function ev(
  event_type: AgentRunEvent['event_type'],
  overrides: Partial<AgentRunEvent> = {},
): AgentRunEvent {
  return {
    event_id: `evt_${Math.random().toString(36).slice(2, 8)}`,
    run_id: 'run_test',
    event_type,
    ...overrides,
  }
}

describe('buildAgentRunTraceFromEvents', () => {
  it('returns running status with empty phases when no events', () => {
    const trace = buildAgentRunTraceFromEvents([], 'run_empty')
    expect(trace.status).toBe('running')
    expect(trace.terminal).toBe(false)
    expect(trace.phases).toHaveLength(0)
    expect(trace.run_id).toBe('run_empty')
  })

  it('builds a complete success flow: planner → tool → run.completed', () => {
    const events: AgentRunEvent[] = [
      ev('planner.started', { message: '正在生成执行计划', created_at: '2026-07-31T00:00:00Z' }),
      ev('planner.completed', {
        message: '计划已生成',
        data: { step_count: 3, duration_ms: 120 },
        created_at: '2026-07-31T00:00:01Z',
      }),
      ev('tool.started', {
        data: { node_id: 'n1', tool_id: 'query_inventory', action: 'query', params: { sku: 'X-100' } },
        created_at: '2026-07-31T00:00:02Z',
      }),
      ev('tool.completed', {
        data: { node_id: 'n1', duration_ms: 220, output_preview: '找到 5 条记录' },
        created_at: '2026-07-31T00:00:03Z',
      }),
      ev('run.completed', {
        message: '执行完成',
        data: { duration_ms: 1420 },
        created_at: '2026-07-31T00:00:04Z',
      }),
    ]

    const trace = buildAgentRunTraceFromEvents(events, 'run_ok')

    expect(trace.status).toBe('success')
    expect(trace.terminal).toBe(true)
    expect(trace.total_duration_ms).toBe(1420)
    expect(trace.phases).toHaveLength(3)

    // planner phase
    expect(trace.phases[0].kind).toBe('planner')
    expect(trace.phases[0].status).toBe('success')
    expect((trace.phases[0] as { step_count?: number }).step_count).toBe(3)
    expect(trace.phases[0].duration_ms).toBe(120)

    // tool phase
    const tool = trace.phases[1]
    expect(tool.kind).toBe('tool')
    expect(tool.status).toBe('success')
    expect(tool.duration_ms).toBe(220)
    if (tool.kind === 'tool') {
      expect(tool.tool_id).toBe('query_inventory')
      expect(tool.node_id).toBe('n1')
      expect(tool.output_preview).toContain('5 条记录')
    }

    // run phase
    const run = trace.phases[2]
    expect(run.kind).toBe('run')
    expect(run.status).toBe('success')
  })

  it('does not turn a completed run into failure when duplicate continue is ignored', () => {
    const trace = buildAgentRunTraceFromEvents([
      ev('planner.completed'),
      ev('run.completed', { message: '执行完成' }),
      ev('run.continue_ignored', { message: '没有等待确认的步骤' }),
    ], 'run_completed')

    expect(trace.status).toBe('success')
    expect(trace.terminal).toBe(true)
    expect(trace.phases.some((phase) => phase.status === 'failed')).toBe(false)
  })

  it('marks run as failed when tool.failed + run.failed arrive', () => {
    const events: AgentRunEvent[] = [
      ev('planner.started'),
      ev('planner.completed'),
      ev('tool.started', { data: { node_id: 'n1', tool_id: 'db_write' } }),
      ev('tool.failed', {
        message: '权限不足',
        data: { node_id: 'n1', duration_ms: 50, error: 'permission denied' },
      }),
      ev('run.failed', {
        message: '执行失败',
        data: { duration_ms: 800 },
      }),
    ]

    const trace = buildAgentRunTraceFromEvents(events, 'run_fail')

    expect(trace.status).toBe('failed')
    expect(trace.terminal).toBe(true)
    expect(trace.total_duration_ms).toBe(800)
    const tool = trace.phases[1]
    expect(tool.kind).toBe('tool')
    if (tool.kind === 'tool') {
      expect(tool.status).toBe('failed')
      expect(tool.error).toContain('权限不足')
    }
  })

  it('sets waiting status when step.waiting_user arrives without terminal', () => {
    const events: AgentRunEvent[] = [
      ev('planner.started'),
      ev('planner.completed'),
      ev('tool.started', { data: { node_id: 'n1', tool_id: 'risky_op' } }),
      ev('step.waiting_user', { message: '需要确认是否执行' }),
    ]

    const trace = buildAgentRunTraceFromEvents(events, 'run_wait')

    expect(trace.status).toBe('waiting')
    expect(trace.terminal).toBe(false)
    const tool = trace.phases[1]
    expect(tool.kind).toBe('tool')
    if (tool.kind === 'tool') {
      expect(tool.waiting_approval).toBe(true)
      expect(tool.status).toBe('waiting')
    }
  })

  it('clears waiting_approval when step.approved arrives', () => {
    const events: AgentRunEvent[] = [
      ev('planner.started'),
      ev('planner.completed'),
      ev('tool.started', { data: { node_id: 'n1', tool_id: 'risky_op' } }),
      ev('step.waiting_user'),
      ev('step.approved'),
      ev('tool.completed', { data: { node_id: 'n1', duration_ms: 100 } }),
    ]

    const trace = buildAgentRunTraceFromEvents(events, 'run_approve')
    expect(trace.status).toBe('running')
    const tool = trace.phases[1]
    expect(tool.kind).toBe('tool')
    if (tool.kind === 'tool') {
      expect(tool.waiting_approval).toBe(false)
      expect(tool.status).toBe('success')
    }
  })

  it('attaches observation.recorded to the most recent open tool phase', () => {
    const events: AgentRunEvent[] = [
      ev('tool.started', { data: { node_id: 'n1', tool_id: 't1' } }),
      ev('observation.recorded', { message: '执行过程中发现异常堆栈' }),
      ev('tool.completed', { data: { node_id: 'n1' } }),
    ]

    const trace = buildAgentRunTraceFromEvents(events, 'run_obs')
    const tool = trace.phases[0]
    if (tool.kind === 'tool') {
      expect(tool.observations).toHaveLength(1)
      expect(tool.observations[0]).toContain('异常堆栈')
    }
  })

  it('counts retries via step.retry_scheduled', () => {
    const events: AgentRunEvent[] = [
      ev('tool.started', { data: { node_id: 'n1', tool_id: 't1' } }),
      ev('step.retry_scheduled'),
      ev('step.retry_scheduled'),
      ev('tool.completed', { data: { node_id: 'n1' } }),
    ]

    const trace = buildAgentRunTraceFromEvents(events, 'run_retry')
    const tool = trace.phases[0]
    if (tool.kind === 'tool') {
      expect(tool.retries).toBe(2)
    }
  })

  it('records llm repair history', () => {
    const events: AgentRunEvent[] = [
      ev('tool.started', { data: { node_id: 'n1', tool_id: 't1' } }),
      ev('step.llm_repair_requested', { message: '请求 LLM 修复' }),
      ev('step.repair_applied', { message: '已应用修复' }),
      ev('tool.completed', { data: { node_id: 'n1' } }),
    ]

    const trace = buildAgentRunTraceFromEvents(events, 'run_repair')
    const tool = trace.phases[0]
    if (tool.kind === 'tool') {
      expect(tool.repair_history).toHaveLength(2)
      expect(tool.repair_history[0]).toContain('请求 LLM')
    }
  })

  it('treats budget.exceeded as terminal failure', () => {
    const events: AgentRunEvent[] = [
      ev('planner.started'),
      ev('tool.started', { data: { node_id: 'n1', tool_id: 't1' } }),
      ev('budget.exceeded', { message: 'AI 预算超限' }),
    ]

    const trace = buildAgentRunTraceFromEvents(events, 'run_budget')
    expect(trace.status).toBe('failed')
    expect(trace.terminal).toBe(true)
    expect(trace.phases.some((p) => p.kind === 'run' && p.status === 'failed')).toBe(true)
  })

  it('treats planner.blocked as terminal failure', () => {
    const events: AgentRunEvent[] = [
      ev('planner.started'),
      ev('planner.blocked', { message: '无法生成计划' }),
    ]

    const trace = buildAgentRunTraceFromEvents(events, 'run_blocked')
    expect(trace.status).toBe('failed')
    expect(trace.terminal).toBe(true)
    const planner = trace.phases[0]
    expect(planner.kind).toBe('planner')
    expect(planner.status).toBe('failed')
  })

  it('handles multiple sequential tool phases', () => {
    const events: AgentRunEvent[] = [
      ev('planner.completed'),
      ev('tool.started', { data: { node_id: 'n1', tool_id: 't1' } }),
      ev('tool.completed', { data: { node_id: 'n1', duration_ms: 100 } }),
      ev('tool.started', { data: { node_id: 'n2', tool_id: 't2' } }),
      ev('tool.completed', { data: { node_id: 'n2', duration_ms: 200 } }),
      ev('run.completed'),
    ]

    const trace = buildAgentRunTraceFromEvents(events, 'run_multi')
    const tools = trace.phases.filter((p) => p.kind === 'tool')
    expect(tools).toHaveLength(2)
    if (tools[0].kind === 'tool') expect(tools[0].duration_ms).toBe(100)
    if (tools[1].kind === 'tool') expect(tools[1].duration_ms).toBe(200)
  })

  it('parses intent from event data when present', () => {
    const events: AgentRunEvent[] = [
      ev('planner.started', { data: { intent: 'shipment_query' } }),
    ]
    const trace = buildAgentRunTraceFromEvents(events, 'run_intent')
    expect(trace.intent).toBe('shipment_query')
  })

  it('merges legacy run.created + planner.started into one planner phase and humanizes titles', () => {
    const events: AgentRunEvent[] = [
      ev('run.created', { message: 'Legacy planner run 已创建' }),
      ev('planner.started', { message: 'Legacy planner 开始执行' }),
      ev('planner.completed', { message: 'Legacy planner 执行完成' }),
      ev('run.completed', {
        message: 'Legacy planner run 执行完成',
        data: {
          chat_payload: { success: true, response: '你好', data: { text: '你好' } },
        },
      }),
    ]
    const trace = buildAgentRunTraceFromEvents(events, 'run_8a030abbf09e43409a7e50205dc5fd18')
    expect(trace.phases.filter((p) => p.kind === 'planner')).toHaveLength(1)
    expect(trace.phases[0].title).toBe('执行计划已生成')
    expect(trace.phases[0].status).toBe('success')
    const run = trace.phases.find((p) => p.kind === 'run')
    expect(run?.title).toBe('智能任务 执行完成')
    if (run?.kind === 'run') {
      // chat_payload 答案已在气泡正文，不再双份塞进 trace
      expect(run.final_output_preview).toBeUndefined()
    }
    expect(trace.intent).toBe('')
    expect(isTrivialChatTrace(trace)).toBe(true)
  })

  it('isTrivialChatTrace is true for single successful read-only tool (customers.query)', () => {
    const events: AgentRunEvent[] = [
      ev('run.created', { message: 'Legacy planner 工具调用已进入 AgentRun 追踪' }),
      ev('tool.started', { data: { node_id: 'n1', tool_id: 'customers', action: 'query' } }),
      ev('tool.completed', { data: { node_id: 'n1', tool_id: 'customers' } }),
      ev('run.completed', {
        message: 'Legacy planner 工具调用追踪完成',
        data: {
          chat_payload: {
            success: true,
            data: { text: '当前共有 20 位客户：\n- A' },
          },
        },
      }),
    ]
    const trace = buildAgentRunTraceFromEvents(events, 'run_customers')
    expect(isTrivialChatTrace(trace)).toBe(true)
    expect(shouldShowAgentRunPlanGraph(trace)).toBe(false)
    const run = trace.phases.find((p) => p.kind === 'run')
    if (run?.kind === 'run') {
      expect(run.final_output_preview).toBeUndefined()
    }
  })

  it('isTrivialChatTrace is false for multi-tool runs (plan graph eligible)', () => {
    const events: AgentRunEvent[] = [
      ev('planner.completed'),
      ev('tool.started', { data: { node_id: 'n1', tool_id: 't1' } }),
      ev('tool.completed', { data: { node_id: 'n1' } }),
      ev('tool.started', { data: { node_id: 'n2', tool_id: 't2' } }),
      ev('tool.completed', { data: { node_id: 'n2' } }),
      ev('run.completed'),
    ]
    const trace = buildAgentRunTraceFromEvents(events, 'run_tools')
    expect(isTrivialChatTrace(trace)).toBe(false)
    expect(shouldShowAgentRunPlanGraph(trace)).toBe(true)
  })

  it('isTrivialChatTrace is false when single tool fails', () => {
    const events: AgentRunEvent[] = [
      ev('tool.started', { data: { node_id: 'n1', tool_id: 't1' } }),
      ev('tool.failed', { data: { node_id: 'n1', error: 'boom' }, message: '失败' }),
      ev('run.failed'),
    ]
    const trace = buildAgentRunTraceFromEvents(events, 'run_fail_tool')
    expect(isTrivialChatTrace(trace)).toBe(false)
    expect(shouldShowAgentRunPlanGraph(trace)).toBe(false)
  })
})

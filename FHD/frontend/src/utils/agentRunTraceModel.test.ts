import { describe, expect, it } from 'vitest'
import type { AgentRunEvent } from '@/api/agentRuns'
import { buildAgentRunTraceFromEvents, isTrivialChatTrace, shouldShowAgentRunPlanGraph } from './agentRunTraceModel'

function ev(event_type: AgentRunEvent['event_type'], overrides: Partial<AgentRunEvent> = {}): AgentRunEvent {
  return {
    event_id: `evt_${Math.random().toString(36).slice(2, 8)}`,
    run_id: 'run_test',
    event_type,
    ...overrides,
  }
}

describe('buildAgentRunTraceFromEvents', () => {
  it('keeps trace identity, errors and zero durations across failed attempts and a successful retry', () => {
    const trace = buildAgentRunTraceFromEvents([
      ev('run.created', { trace_id: 'trace-a', data: { task_id: 'task-a' } }),
      ev('tool.started', { data: { trace_id: 'trace-a', span_id: 'span-a', node_id: 'a' } }),
      ev('tool.failed', { data: { node_id: 'a', error_code: 'tool_timeout', error_type: 'TimeoutError', duration_ms: 0 } }),
      ev('tool.started', { data: { node_id: 'b' } }),
      ev('step.retry_scheduled', { data: { node_id: 'a' } }),
      ev('step.llm_repair_requested', { data: { node_id: 'a' }, message: '重试前核对参数' }),
      ev('observation.recorded', { data: { node_id: 'a' }, message: '已确认未写入' }),
      ev('tool.started', { data: { node_id: 'a', trace_id: 'trace-a', span_id: 'span-retry', attempt: 2 } }),
      ev('tool.completed', { data: { node_id: 'a', duration_ms: 0 } }),
      ev('tool.completed', { data: { node_id: 'b', duration_ms: 1 } }),
      ev('run.completed', { data: { trace_id: 'trace-a', duration_ms: 100 } }),
    ], 'run_test')
    expect(trace).toMatchObject({ trace_id: 'trace-a', status: 'success', total_duration_ms: 100 })
    expect(trace.phases[1]).toMatchObject({ span_id: 'span-a', status: 'failed', error_code: 'tool_timeout',
      error_type: 'TimeoutError', duration_ms: 0, retries: 1, repair_history: ['重试前核对参数'], observations: ['已确认未写入'] })
    expect(trace.phases[2]).toMatchObject({ node_id: 'b', retries: 0, repair_history: [] })
    expect(trace.phases[3]).toMatchObject({ span_id: 'span-retry', attempt: 2, status: 'success', duration_ms: 0 })
  })

  it.each([undefined, null, '', -1, NaN, Infinity])('does not turn invalid duration %s into a measurement', duration_ms => {
    const trace = buildAgentRunTraceFromEvents([ev('run.failed', { data: { duration_ms } })], 'run_test')
    expect(trace.total_duration_ms).toBeUndefined()
    expect(trace.phases[0].duration_ms).toBeUndefined()
  })

  it('does not treat a transport done event as business completion', () => {
    const trace = buildAgentRunTraceFromEvents([
      ev('tool.started', { data: { node_id: 'a' } }), ev('done', { data: { success: true } }),
    ], 'run_test')
    expect(trace).toMatchObject({ status: 'running', terminal: false })
    expect(trace.phases[0].status).toBe('running')
  })

  it('deduplicates reconnect events and matches overlapping attempts by call identity', () => {
    const retry = ev('step.retry_scheduled', { data: { node_id: 'a' } })
    const trace = buildAgentRunTraceFromEvents([
      ev('tool.started', { data: { node_id: 'a', call_id: 'first' } }), retry, retry,
      ev('tool.started', { data: { node_id: 'a', call_id: 'second' } }),
      ev('tool.failed', { data: { node_id: 'a', call_id: 'first', error_code: 'timeout' } }),
      ev('tool.completed', { data: { node_id: 'a', call_id: 'second' } }),
    ], 'run_test')
    expect(trace.phases).toHaveLength(2)
    expect(trace.phases[0]).toMatchObject({ call_id: 'first', status: 'failed', retries: 1 })
    expect(trace.phases[1]).toMatchObject({ call_id: 'second', status: 'success', retries: 0 })
  })

  it('clears aggregate failure codes after recovery and updates the terminal row only with final measured duration', () => {
    const events = [
      ev('run.observed', { data: { phase: 'execution', status: 'failed', duration_ms: 100,
        error_code: 'agent_phase_failed', error_type: 'TimeoutError', duration_scope: 'active', trace_id: 'legacy-run-observation' } }),
      ev('run.observed', { data: { phase: 'planning', status: 'planning', duration_ms: 120, phase_duration_ms: 20 } }),
      ev('run.completed'),
    ]
    const before = buildAgentRunTraceFromEvents(events, 'run_test')
    expect(before.phases.at(-1)?.duration_ms).toBeUndefined()
    expect(before.error_code).toBeUndefined()
    expect(before.error_type).toBeUndefined()
    events.push(ev('run.observed', { data: { phase: 'execution', status: 'completed', duration_ms: 400, duration_scope: 'active', trace_id: 'a'.repeat(32) } }))
    const trace = buildAgentRunTraceFromEvents(events, 'run_test')
    expect(trace).toMatchObject({ status: 'success', total_duration_ms: 400, trace_id: 'a'.repeat(32) })
    expect(trace.phases.at(-1)?.duration_ms).toBe(400)
    expect(trace.error_code).toBeUndefined()
    expect(trace.error_type).toBeUndefined()
    expect(trace.phases[0].error_code).toBe('agent_phase_failed')
    expect(trace.phases[0].trace_id).toBe('legacy-run-observation')
    const observedOnly = buildAgentRunTraceFromEvents([events[0], events[3]], 'run_test')
    expect(observedOnly.status).toBe('success')
    expect(observedOnly.error_code).toBeUndefined()
    expect(observedOnly.error_type).toBeUndefined()
  })

  it.each([
    ['completed', 'success', true], ['failed', 'failed', true], ['blocked', 'blocked', false],
    ['waiting_user', 'waiting', false], ['paused', 'paused', false], ['cancelled', 'cancelled', true],
    ['rejected', 'blocked', true], ['', 'running', false],
  ])('observed status %s records active time without assuming completion', (status, expected, terminal) => {
    const trace = buildAgentRunTraceFromEvents([
      ev('planner.started'),
      ev('run.observed', { data: { status, duration_ms: 0, duration_scope: 'active', trace_id: 'trace-a', task_id: 'task-a' } }),
    ], 'run_test')
    expect(trace).toMatchObject({ status: expected, terminal, total_duration_ms: 0, duration_scope: 'active',
      trace_id: 'trace-a', task_id: 'task-a' })
  })

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
        data: {
          node_id: 'n1',
          tool_id: 'query_inventory',
          action: 'query',
          params: { sku: 'X-100' },
        },
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

  it('shows the concrete failure reason instead of the generic event title', () => {
    const events: AgentRunEvent[] = [
      ev('tool.started', { data: { node_id: 'n1', tool_id: 'elt_import', action: 'execute' } }),
      ev('tool.failed', {
        message: 'elt_import.execute 执行失败',
        data: {
          node_id: 'n1',
          tool_id: 'elt_import',
          action: 'execute',
          error: '预演存在错误行；默认阻断整批。',
          reason: '预演存在错误行；默认阻断整批。',
        },
      }),
    ]

    const trace = buildAgentRunTraceFromEvents(events, 'run_elt')

    const tool = trace.phases[0]
    if (tool.kind === 'tool') {
      expect(tool.status).toBe('failed')
      expect(tool.error).toContain('预演存在错误行')
      expect(tool.error).not.toBe('elt_import.execute 执行失败')
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
    const events: AgentRunEvent[] = [ev('planner.started'), ev('planner.blocked', { message: '无法生成计划' })]

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
    const events: AgentRunEvent[] = [ev('planner.started', { data: { intent: 'shipment_query' } })]
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

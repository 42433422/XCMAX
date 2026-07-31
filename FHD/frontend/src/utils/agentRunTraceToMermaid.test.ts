import { describe, expect, it } from 'vitest'
import { traceToMermaid } from './agentRunTraceToMermaid'
import type { AgentRunTraceData } from './agentRunTraceModel'

function makeTrace(overrides: Partial<AgentRunTraceData> = {}): AgentRunTraceData {
  return {
    run_id: 'run_test',
    intent: 'test_intent',
    status: 'running',
    phases: [],
    terminal: false,
    ...overrides,
  }
}

describe('traceToMermaid', () => {
  it('returns empty string for null/undefined/empty trace', () => {
    expect(traceToMermaid(null)).toBe('')
    expect(traceToMermaid(undefined)).toBe('')
    expect(traceToMermaid(makeTrace({ phases: [] }))).toBe('')
  })

  it('generates flowchart TD header', () => {
    const trace = makeTrace({
      phases: [
        {
          kind: 'planner',
          status: 'success',
          started_event_id: 'e1',
          title: '执行计划',
        },
      ],
    })
    const out = traceToMermaid(trace)
    expect(out.startsWith('flowchart TD')).toBe(true)
    expect(out).toContain('p0([执行计划])')
    expect(out).toContain('class p0 st-success')
  })

  it('renders tool phase as subroutine shape', () => {
    const trace = makeTrace({
      phases: [
        {
          kind: 'tool',
          status: 'running',
          started_event_id: 'e1',
          node_id: 'n1',
          tool_id: 'query_inventory',
          action: 'query',
          title: 'query_inventory',
          observations: [],
          waiting_approval: false,
          retries: 0,
          repair_history: [],
        },
      ],
    })
    const out = traceToMermaid(trace)
    expect(out).toContain('p0[[query_inventory]]')
    expect(out).toContain('class p0 st-running')
  })

  it('renders run phase as circle shape', () => {
    const trace = makeTrace({
      phases: [
        {
          kind: 'run',
          status: 'success',
          started_event_id: 'e1',
          title: '执行完成',
        },
      ],
    })
    const out = traceToMermaid(trace)
    expect(out).toContain('p0(((执行完成)))')
  })

  it('connects adjacent phases with arrows', () => {
    const trace = makeTrace({
      phases: [
        { kind: 'planner', status: 'success', started_event_id: 'e1', title: 'p1' },
        { kind: 'tool', status: 'success', started_event_id: 'e2', node_id: 'n1', tool_id: 't1', action: 'a', title: 't1', observations: [], waiting_approval: false, retries: 0, repair_history: [] },
        { kind: 'run', status: 'success', started_event_id: 'e3', title: 'done' },
      ],
    })
    const out = traceToMermaid(trace)
    expect(out).toContain('p0 --> p1')
    expect(out).toContain('p1 --> p2')
  })

  it('labels failed edges with 失败', () => {
    const trace = makeTrace({
      phases: [
        { kind: 'planner', status: 'success', started_event_id: 'e1', title: 'p1' },
        { kind: 'tool', status: 'failed', started_event_id: 'e2', node_id: 'n1', tool_id: 't1', action: 'a', title: 't1', observations: [], waiting_approval: false, retries: 0, repair_history: [] },
      ],
    })
    const out = traceToMermaid(trace)
    expect(out).toContain('p0 -->|失败| p1')
  })

  it('labels waiting edges with 等待', () => {
    const trace = makeTrace({
      phases: [
        { kind: 'planner', status: 'success', started_event_id: 'e1', title: 'p1' },
        { kind: 'tool', status: 'waiting', started_event_id: 'e2', node_id: 'n1', tool_id: 't1', action: 'a', title: 't1', observations: [], waiting_approval: true, retries: 0, repair_history: [] },
      ],
    })
    const out = traceToMermaid(trace)
    expect(out).toContain('p0 -->|等待| p1')
  })

  it('includes all 5 classDef styles', () => {
    const trace = makeTrace({
      phases: [
        { kind: 'planner', status: 'running', started_event_id: 'e1', title: 'p' },
      ],
    })
    const out = traceToMermaid(trace)
    expect(out).toContain('classDef st-running')
    expect(out).toContain('classDef st-success')
    expect(out).toContain('classDef st-failed')
    expect(out).toContain('classDef st-waiting')
    expect(out).toContain('classDef st-blocked')
  })

  it('escapes brackets in labels', () => {
    const trace = makeTrace({
      phases: [
        {
          kind: 'tool',
          status: 'success',
          started_event_id: 'e1',
          node_id: 'n1',
          tool_id: 'query[db]',
          action: 'a',
          title: 'query[db]',
          observations: [],
          waiting_approval: false,
          retries: 0,
          repair_history: [],
        },
      ],
    })
    const out = traceToMermaid(trace)
    // 方括号被替换为圆括号避免破坏 mermaid 语法
    expect(out).toContain('query(db)')
    expect(out).not.toContain('query[db]')
  })
})

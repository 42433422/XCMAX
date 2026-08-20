import { describe, expect, it } from 'vitest'
import { traceToMermaid } from './agentRunTraceToMermaid'
import type { AgentRunTraceData, TraceToolPhase } from './agentRunTraceModel'

function toolPhase(overrides: Partial<TraceToolPhase> & Pick<TraceToolPhase, 'node_id' | 'tool_id'>): TraceToolPhase {
  return {
    kind: 'tool',
    status: 'success',
    started_event_id: overrides.started_event_id || overrides.node_id,
    title: overrides.tool_id,
    action: 'a',
    observations: [],
    waiting_approval: false,
    retries: 0,
    repair_history: [],
    ...overrides,
  }
}

function makeTrace(overrides: Partial<AgentRunTraceData> = {}): AgentRunTraceData {
  return {
    run_id: 'run_test',
    intent: 'test_intent',
    status: 'success',
    phases: [],
    terminal: true,
    ...overrides,
  }
}

/** 多工具成功轨迹：才允许生成计划图 */
function multiToolTrace(extraPhases: AgentRunTraceData['phases'] = []): AgentRunTraceData {
  return makeTrace({
    phases: [
      { kind: 'planner', status: 'success', started_event_id: 'e0', title: '执行计划' },
      toolPhase({ node_id: 'n1', tool_id: 't1', started_event_id: 'e1' }),
      toolPhase({ node_id: 'n2', tool_id: 't2', started_event_id: 'e2' }),
      ...extraPhases,
    ],
  })
}

describe('traceToMermaid', () => {
  it('returns empty string for null/undefined/empty/trivial traces', () => {
    expect(traceToMermaid(null)).toBe('')
    expect(traceToMermaid(undefined)).toBe('')
    expect(traceToMermaid(makeTrace({ phases: [] }))).toBe('')
    // 单工具成功：不生成图
    expect(
      traceToMermaid(
        makeTrace({
          phases: [toolPhase({ node_id: 'n1', tool_id: 'customers' })],
        }),
      ),
    ).toBe('')
    // 仅 planner：trivial
    expect(
      traceToMermaid(
        makeTrace({
          phases: [{ kind: 'planner', status: 'success', started_event_id: 'e1', title: '执行计划' }],
        }),
      ),
    ).toBe('')
  })

  it('generates flowchart TD for multi-tool runs', () => {
    const out = traceToMermaid(multiToolTrace())
    expect(out.startsWith('flowchart TD')).toBe(true)
    expect(out).toContain('p0([执行计划])')
    expect(out).toContain('class p0 st-success')
  })

  it('renders tool phase as subroutine shape', () => {
    const out = traceToMermaid(
      makeTrace({
        phases: [
          toolPhase({ node_id: 'n1', tool_id: 'query_inventory', status: 'running' }),
          toolPhase({ node_id: 'n2', tool_id: 't2', status: 'running' }),
        ],
        status: 'running',
        terminal: false,
      }),
    )
    expect(out).toContain('p0[[query_inventory]]')
    expect(out).toContain('class p0 st-running')
  })

  it('renders run phase as circle shape', () => {
    const out = traceToMermaid(multiToolTrace([{ kind: 'run', status: 'success', started_event_id: 'e9', title: '执行完成' }]))
    expect(out).toContain('(((执行完成)))')
  })

  it('connects adjacent phases with arrows', () => {
    const out = traceToMermaid(multiToolTrace([{ kind: 'run', status: 'success', started_event_id: 'e3', title: 'done' }]))
    expect(out).toContain('p0 --> p1')
    expect(out).toContain('p1 --> p2')
  })

  it('labels failed edges with 失败', () => {
    const out = traceToMermaid(
      makeTrace({
        status: 'failed',
        phases: [
          { kind: 'planner', status: 'success', started_event_id: 'e1', title: 'p1' },
          toolPhase({ node_id: 'n1', tool_id: 't1', status: 'failed' }),
          toolPhase({ node_id: 'n2', tool_id: 't2', status: 'success' }),
        ],
      }),
    )
    expect(out).toContain('p0 -->|失败| p1')
  })

  it('labels waiting edges with 等待', () => {
    const out = traceToMermaid(
      makeTrace({
        status: 'waiting',
        terminal: false,
        phases: [
          { kind: 'planner', status: 'success', started_event_id: 'e1', title: 'p1' },
          toolPhase({
            node_id: 'n1',
            tool_id: 't1',
            status: 'waiting',
            waiting_approval: true,
          }),
          toolPhase({ node_id: 'n2', tool_id: 't2', status: 'running' }),
        ],
      }),
    )
    expect(out).toContain('p0 -->|等待| p1')
  })

  it('includes all 5 classDef styles', () => {
    const out = traceToMermaid(multiToolTrace())
    expect(out).toContain('classDef st-running')
    expect(out).toContain('classDef st-success')
    expect(out).toContain('classDef st-failed')
    expect(out).toContain('classDef st-waiting')
    expect(out).toContain('classDef st-blocked')
  })

  it('escapes brackets in labels', () => {
    const out = traceToMermaid(
      makeTrace({
        phases: [toolPhase({ node_id: 'n1', tool_id: 'query[db]' }), toolPhase({ node_id: 'n2', tool_id: 't2' })],
      }),
    )
    expect(out).toContain('query(db)')
    expect(out).not.toContain('query[db]')
  })
})

import { describe, expect, it } from 'vitest'
import { executionGraph } from './executionGraph'
import type { AgentRunStep } from '@/api/agentRuns'
const step = (id: string, depends_on: string[] = [], status = 'pending'): AgentRunStep => ({
  step_id: id,
  node_id: id,
  tool_id: 'employee',
  action: 'execute',
  depends_on,
  status,
})
describe('persisted execution graph', () => {
  it('shows only recorded dependencies, preserving parallel branches', () => {
    const graph = executionGraph([step('a'), step('b', ['a'], 'running'), step('c', ['a']), step('d', ['b', 'c'])])
    expect(graph.edges.map((e) => `${e.source}:${e.target}`)).toEqual(['a:b', 'a:c', 'b:d', 'c:d'])
    expect(graph.nodes.find((n) => n.id === 'a')!.position.x).toBeLessThan(graph.nodes.find((n) => n.id === 'b')!.position.x)
    expect(graph.nodes.find((n) => n.id === 'b')!.position.x).toEqual(graph.nodes.find((n) => n.id === 'c')!.position.x)
    expect(graph.edges.find((e) => e.target === 'b')!.animated).toBe(true)
  })
  it('does not invent a serial flow for unrelated steps or dangling dependencies', () => {
    const graph = executionGraph([step('a'), step('b', ['missing', 'b'])])
    expect(graph.edges).toEqual([])
    expect(graph.nodes).toHaveLength(2)
  })
  it('keeps failures visible instead of painting completion', () => {
    const graph = executionGraph([step('a', [], 'failed'), step('b', ['a'], 'skipped')])
    expect(graph.nodes[0].label).toContain('失败')
    expect(graph.nodes[1].label).toContain('已跳过')
    expect(executionGraph([])).toEqual({ nodes: [], edges: [] })
  })
})

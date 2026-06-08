import { describe, expect, it } from 'vitest'
import { computeGraphSummary, buildMermaidFlowchart } from './workflowMermaid'

describe('computeGraphSummary', () => {
  it('returns empty counts for empty input', () => {
    const result = computeGraphSummary([], [])
    expect(result.counts).toEqual({})
    expect(result.warnings).toContain('缺少开始节点')
    expect(result.unreachableIds).toEqual([])
  })

  it('counts node types', () => {
    const nodes = [
      { id: 1, node_type: 'start', name: 'Start' },
      { id: 2, node_type: 'task', name: 'Task' },
      { id: 3, node_type: 'end', name: 'End' },
    ]
    const result = computeGraphSummary(nodes, [])
    expect(result.counts).toEqual({ start: 1, task: 1, end: 1 })
  })

  it('warns about missing start node', () => {
    const nodes = [{ id: 1, node_type: 'task', name: 'Task' }]
    const result = computeGraphSummary(nodes, [])
    expect(result.warnings).toContain('缺少开始节点')
  })

  it('warns about multiple start nodes', () => {
    const nodes = [
      { id: 1, node_type: 'start', name: 'S1' },
      { id: 2, node_type: 'start', name: 'S2' },
    ]
    const result = computeGraphSummary(nodes, [])
    expect(result.warnings.some((w) => w.includes('开始节点数量'))).toBe(true)
  })

  it('warns about edges referencing missing nodes', () => {
    const nodes = [{ id: 1, node_type: 'start', name: 'S' }]
    const edges = [{ id: 'e1', source_node_id: 1, target_node_id: 99 }]
    const result = computeGraphSummary(nodes, edges)
    expect(result.warnings.some((w) => w.includes('缺失节点'))).toBe(true)
  })

  it('warns about nodes with no outgoing edges', () => {
    const nodes = [
      { id: 1, node_type: 'start', name: 'S' },
      { id: 2, node_type: 'task', name: 'T' },
    ]
    const edges = [{ id: 'e1', source_node_id: 1, target_node_id: 2 }]
    const result = computeGraphSummary(nodes, edges)
    expect(result.warnings.some((w) => w.includes('无出边'))).toBe(true)
  })

  it('detects unreachable nodes', () => {
    const nodes = [
      { id: 1, node_type: 'start', name: 'S' },
      { id: 2, node_type: 'end', name: 'E' },
      { id: 3, node_type: 'task', name: 'Orphan' },
    ]
    const edges = [{ id: 'e1', source_node_id: 1, target_node_id: 2 }]
    const result = computeGraphSummary(nodes, edges)
    expect(result.unreachableIds).toContain(3)
  })

  it('handles null and undefined inputs', () => {
    const result = computeGraphSummary(null, undefined)
    expect(result.counts).toEqual({})
  })

  it('handles non-array inputs', () => {
    const result = computeGraphSummary('not-array', 42)
    expect(result.counts).toEqual({})
  })

  it('counts unknown type for nodes without node_type', () => {
    const nodes = [{ id: 1, name: 'NoType' }]
    const result = computeGraphSummary(nodes, [])
    expect(result.counts).toEqual({ unknown: 1 })
  })
})

describe('buildMermaidFlowchart', () => {
  it('returns empty placeholder for no nodes', () => {
    const result = buildMermaidFlowchart([], [])
    expect(result).toContain('flowchart TD')
    expect(result).toContain('无节点')
  })

  it('builds flowchart with nodes', () => {
    const nodes = [
      { id: 's1', node_type: 'start', name: 'Start' },
      { id: 'e1', node_type: 'end', name: 'End' },
    ]
    const result = buildMermaidFlowchart(nodes, [])
    expect(result).toContain('flowchart TD')
    expect(result).toContain('Start (start)')
    expect(result).toContain('End (end)')
  })

  it('builds flowchart with edges', () => {
    const nodes = [
      { id: 's1', node_type: 'start', name: 'Start' },
      { id: 'e1', node_type: 'end', name: 'End' },
    ]
    const edges = [{ source_node_id: 's1', target_node_id: 'e1' }]
    const result = buildMermaidFlowchart(nodes, edges)
    expect(result).toContain('-->')
  })

  it('includes condition on edges', () => {
    const nodes = [
      { id: 's1', node_type: 'start', name: 'Start' },
      { id: 'e1', node_type: 'end', name: 'End' },
    ]
    const edges = [{ source_node_id: 's1', target_node_id: 'e1', condition: 'approved' }]
    const result = buildMermaidFlowchart(nodes, edges)
    expect(result).toContain('approved')
  })

  it('sanitizes special characters in IDs', () => {
    const nodes = [{ id: 'node/1', node_type: 'task', name: 'Task' }]
    const result = buildMermaidFlowchart(nodes, [])
    expect(result).toContain('N_node_1')
  })

  it('handles null and undefined inputs', () => {
    const result = buildMermaidFlowchart(null, undefined)
    expect(result).toContain('无节点')
  })
})

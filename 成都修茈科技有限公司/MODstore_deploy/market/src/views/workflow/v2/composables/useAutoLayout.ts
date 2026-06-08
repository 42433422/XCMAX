/**
 * 用 @dagrejs/dagre 计算节点的层次化位置。
 * 对接 Vue Flow 的 nodes/edges，返回新坐标 map。
 */

import dagre from '@dagrejs/dagre'
import type { Edge, Node } from '@vue-flow/core'

export interface LayoutOptions {
  direction?: 'LR' | 'TB'
  nodeWidth?: number
  nodeHeight?: number
  rankSep?: number
  nodeSep?: number
}

export function computeAutoLayout(
  nodes: Node[],
  edges: Edge[],
  opts: LayoutOptions = {},
): Map<string, { x: number; y: number }> {
  const {
    direction = 'LR',
    nodeWidth = 220,
    nodeHeight = 92,
    rankSep = 80,
    nodeSep = 48,
  } = opts

  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: direction, ranksep: rankSep, nodesep: nodeSep })

  for (const n of nodes) {
    g.setNode(n.id, { width: nodeWidth, height: nodeHeight })
  }
  for (const e of edges) {
    g.setEdge(e.source, e.target)
  }

  dagre.layout(g)

  const result = new Map<string, { x: number; y: number }>()
  for (const n of nodes) {
    const pos = g.node(n.id)
    if (!pos) continue
    result.set(n.id, {
      x: pos.x - nodeWidth / 2,
      y: pos.y - nodeHeight / 2,
    })
  }
  return result
}

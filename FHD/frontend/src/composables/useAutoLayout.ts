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

export interface GridLayoutOptions {
  cols: number
  cellWidth: number
  cellHeight: number
  gapX?: number
  gapY?: number
  paddingX?: number
  paddingY?: number
  paddingBottom?: number
}

/** 固定列数网格；返回子项坐标与容器宽高（用于 Vue Flow group 节点）。 */
export function computeGridLayout(
  ids: string[],
  opts: GridLayoutOptions,
): { positions: Map<string, { x: number; y: number }>; width: number; height: number } {
  const {
    cols,
    cellWidth,
    cellHeight,
    gapX = 12,
    gapY = 12,
    paddingX = 14,
    paddingY = 36,
    paddingBottom = 14,
  } = opts

  const positions = new Map<string, { x: number; y: number }>()
  const rowCount = Math.max(1, Math.ceil(Math.max(ids.length, 1) / cols))

  ids.forEach((id, i) => {
    const col = i % cols
    const row = Math.floor(i / cols)
    positions.set(id, {
      x: paddingX + col * (cellWidth + gapX),
      y: paddingY + row * (cellHeight + gapY),
    })
  })

  const width = paddingX * 2 + cols * cellWidth + (cols - 1) * gapX
  const height = paddingY + rowCount * cellHeight + (rowCount - 1) * gapY + paddingBottom
  return { positions, width, height }
}

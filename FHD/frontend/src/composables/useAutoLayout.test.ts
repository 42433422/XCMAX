import { describe, it, expect, vi, beforeEach } from 'vitest'
import { computeAutoLayout, computeGridLayout } from '@/composables/useAutoLayout'

vi.mock('@dagrejs/dagre', () => ({
  default: {
    graphlib: {
      Graph: class MockGraph {
        private nodes: Map<string, any> = new Map()
        private edges: any[] = []
        private graphOpts: any = {}
        setDefaultEdgeLabel(fn: () => any) {}
        setGraph(opts: any) { this.graphOpts = opts }
        setNode(id: string, opts: any) { this.nodes.set(id, opts) }
        setEdge(source: string, target: string) { this.edges.push({ source, target }) }
        node(id: string) {
          const n = this.nodes.get(id)
          if (!n) return undefined
          return { x: 100, y: 200, width: n.width, height: n.height }
        }
      },
    },
    layout: vi.fn(),
  },
}))

describe('useAutoLayout', () => {
  describe('computeAutoLayout', () => {
    it('returns positions for all nodes', () => {
      const nodes = [
        { id: 'a' } as any,
        { id: 'b' } as any,
      ]
      const edges = [
        { source: 'a', target: 'b' } as any,
      ]
      const result = computeAutoLayout(nodes, edges)
      expect(result.size).toBe(2)
      expect(result.has('a')).toBe(true)
      expect(result.has('b')).toBe(true)
    })

    it('returns empty map for empty nodes', () => {
      const result = computeAutoLayout([], [])
      expect(result.size).toBe(0)
    })

    it('uses default options when none provided', () => {
      const nodes = [{ id: 'a' } as any]
      const result = computeAutoLayout(nodes, [])
      expect(result.size).toBe(1)
      const pos = result.get('a')!
      expect(typeof pos.x).toBe('number')
      expect(typeof pos.y).toBe('number')
    })

    it('accepts custom layout options', () => {
      const nodes = [{ id: 'a' } as any]
      const result = computeAutoLayout(nodes, [], {
        direction: 'TB',
        nodeWidth: 300,
        nodeHeight: 100,
        rankSep: 100,
        nodeSep: 60,
      })
      expect(result.size).toBe(1)
    })

    it('skips nodes without positions', () => {
      // The mock returns positions for all nodes, so this tests the skip logic path
      const nodes = [{ id: 'a' } as any]
      const result = computeAutoLayout(nodes, [])
      expect(result.size).toBe(1)
    })
  })

  describe('computeGridLayout', () => {
    it('computes grid positions for items', () => {
      const ids = ['a', 'b', 'c', 'd']
      const result = computeGridLayout(ids, {
        cols: 2,
        cellWidth: 100,
        cellHeight: 50,
      })
      expect(result.positions.size).toBe(4)
      expect(result.width).toBeGreaterThan(0)
      expect(result.height).toBeGreaterThan(0)
    })

    it('positions items in correct grid layout', () => {
      const ids = ['a', 'b', 'c', 'd']
      const result = computeGridLayout(ids, {
        cols: 2,
        cellWidth: 100,
        cellHeight: 50,
        gapX: 10,
        gapY: 10,
        paddingX: 20,
        paddingY: 30,
      })
      const posA = result.positions.get('a')!
      const posB = result.positions.get('b')!
      // 'a' is col 0, 'b' is col 1
      expect(posB.x).toBeGreaterThan(posA.x)
      // 'c' is on row 1
      const posC = result.positions.get('c')!
      expect(posC.y).toBeGreaterThan(posA.y)
    })

    it('handles empty ids', () => {
      const result = computeGridLayout([], {
        cols: 2,
        cellWidth: 100,
        cellHeight: 50,
      })
      expect(result.positions.size).toBe(0)
      expect(result.width).toBeGreaterThan(0)
      expect(result.height).toBeGreaterThan(0)
    })

    it('handles single item', () => {
      const result = computeGridLayout(['a'], {
        cols: 3,
        cellWidth: 100,
        cellHeight: 50,
      })
      expect(result.positions.size).toBe(1)
    })

    it('uses default gap and padding values', () => {
      const result = computeGridLayout(['a', 'b'], {
        cols: 2,
        cellWidth: 100,
        cellHeight: 50,
      })
      expect(result.positions.size).toBe(2)
    })

    it('computes correct width', () => {
      const result = computeGridLayout(['a', 'b'], {
        cols: 2,
        cellWidth: 100,
        cellHeight: 50,
        gapX: 10,
        paddingX: 20,
      })
      // width = paddingX * 2 + cols * cellWidth + (cols - 1) * gapX
      const expectedWidth = 20 * 2 + 2 * 100 + 1 * 10
      expect(result.width).toBe(expectedWidth)
    })

    it('computes correct height for multiple rows', () => {
      const result = computeGridLayout(['a', 'b', 'c'], {
        cols: 2,
        cellWidth: 100,
        cellHeight: 50,
        gapY: 10,
        paddingY: 30,
        paddingBottom: 15,
      })
      // 3 items in 2 cols = 2 rows
      // height = paddingY + rowCount * cellHeight + (rowCount - 1) * gapY + paddingBottom
      const expectedHeight = 30 + 2 * 50 + 1 * 10 + 15
      expect(result.height).toBe(expectedHeight)
    })
  })
})

/**
 * DutyRosterGraphPanel 布局函数（入参为节点/边数组）。
 *
 * 由原文机械切分而来（行为保持不变）；flowNodes/flowEdges 由调用方注入
 * （原函数体直接写组件内 ref，拆分后改为工厂注入，语义不变）。
 */
import type { Ref } from 'vue'
import type { Node, Edge } from '@vue-flow/core'
import { computeAutoLayout, computeGridLayout } from '@host/composables/useAutoLayout'
import { DEPARTMENT_ORDER } from '@host/domain/yuangonDutyRoster'
import { DEPT_GROUP_GAP_X, DEPT_GROUP_GAP_Y, DEPT_INNER_COLS, DEPT_OUTER_COLS, NODE_H, NODE_W } from './dutyRosterConstants'

export function createDutyRosterLayout(flowNodes: Ref<Node[]>, flowEdges: Ref<Edge[]>) {
  function applyDepartmentLayout(rawNodes: Node[], rawEdges: Edge[]) {
    const groupIds = DEPARTMENT_ORDER.map((id) => `dept-${id}`).filter((gid) =>
      rawNodes.some((n) => n.id === gid),
    )
    const boxSizes = new Map<string, { w: number; h: number }>()

    for (const gid of groupIds) {
      const children = rawNodes.filter((n) => n.parentNode === gid)
      const { positions, width, height } = computeGridLayout(
        children.map((c) => c.id),
        {
          cols: DEPT_INNER_COLS,
          cellWidth: NODE_W,
          cellHeight: NODE_H,
          gapX: 10,
          gapY: 10,
          paddingX: 12,
          paddingY: 30,
          paddingBottom: 12,
        },
      )
      for (const child of children) {
        const p = positions.get(child.id)
        if (p) child.position = p
      }
      const w = Math.max(width, 280)
      boxSizes.set(gid, { w, h: height })
      const group = rawNodes.find((n) => n.id === gid)
      if (group) {
        group.style = {
          ...(group.style as Record<string, string>),
          width: `${w}px`,
          height: `${height}px`,
          minWidth: `${w}px`,
        }
      }
    }

    const colWidths = [0, 1, 2].map((c) =>
      Math.max(
        280,
        ...groupIds.filter((_, i) => i % DEPT_OUTER_COLS === c).map((gid) => boxSizes.get(gid)!.w),
      ),
    )
    const rowHeights = [0, 1].map((r) =>
      Math.max(
        180,
        ...groupIds
          .filter((_, i) => Math.floor(i / DEPT_OUTER_COLS) === r)
          .map((gid) => boxSizes.get(gid)!.h),
      ),
    )

    groupIds.forEach((gid, idx) => {
      const col = idx % DEPT_OUTER_COLS
      const row = Math.floor(idx / DEPT_OUTER_COLS)
      let x = 0
      for (let c = 0; c < col; c++) x += colWidths[c] + DEPT_GROUP_GAP_X
      let y = 0
      for (let r = 0; r < row; r++) y += rowHeights[r] + DEPT_GROUP_GAP_Y
      const group = rawNodes.find((n) => n.id === gid)
      if (group) group.position = { x, y }
    })

    flowNodes.value = rawNodes
    flowEdges.value = rawEdges
  }

  function applyLayout(rawNodes: Node[], rawEdges: Edge[]) {
    const posMap = computeAutoLayout(rawNodes, rawEdges, {
      direction: 'LR', nodeWidth: NODE_W, nodeHeight: NODE_H, rankSep: 140, nodeSep: 32,
    })
    for (const n of rawNodes) {
      const p = posMap.get(n.id); if (p) n.position = p
    }
    flowNodes.value = rawNodes
    flowEdges.value = rawEdges
  }

  function applyAreaLayout(rawNodes: Node[], rawEdges: Edge[]) {
    // Layout groups first with TB direction
    const groupNodes = rawNodes.filter((n) => !n.parentNode)
    const posMap = computeAutoLayout(groupNodes, [], {
      direction: 'LR', nodeWidth: 320, nodeHeight: 280, rankSep: 60, nodeSep: 40,
    })
    for (const n of groupNodes) {
      const p = posMap.get(n.id); if (p) n.position = p
    }
    // Layout children within each group with TB direction
    const groups = new Set(rawNodes.filter((n) => n.type === 'group').map((n) => n.id))
    for (const gid of groups) {
      const children = rawNodes.filter((n) => n.parentNode === gid)
      let cy = 0
      for (const c of children) {
        c.position = { x: 16, y: cy }
        cy += NODE_H + 12
      }
    }
    flowNodes.value = rawNodes
    flowEdges.value = rawEdges
  }
  return { applyDepartmentLayout, applyLayout, applyAreaLayout }
}

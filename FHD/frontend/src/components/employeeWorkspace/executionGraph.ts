import dagre from '@dagrejs/dagre'
import type { Node, Edge } from '@vue-flow/core'
import type { AgentRunStep } from '@/api/agentRuns'
import { taskStatusLabel } from '@/utils/taskWorkspacePresentation'

/** Layout is delegated to Dagre; topology and states come only from persisted steps. */
export function executionGraph(steps: AgentRunStep[]): { nodes: Node[]; edges: Edge[] } {
  const layout = new dagre.graphlib.Graph()
  layout.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 70 })
  layout.setDefaultEdgeLabel(() => ({}))
  const ids = new Set(steps.map((s) => s.node_id || s.step_id))
  const edges: Edge[] = []
  for (const step of steps) layout.setNode(step.node_id || step.step_id, { width: 252, height: 100 })
  for (const step of steps) {
    const target = step.node_id || step.step_id
    for (const source of new Set(step.depends_on || [])) {
      if (!ids.has(source) || source === target) continue
      layout.setEdge(source, target)
      edges.push({
        id: `${source}:${target}`,
        source,
        target,
        type: 'smoothstep',
        markerEnd: 'arrowclosed',
        animated: step.status === 'running',
      })
    }
  }
  dagre.layout(layout)
  return {
    nodes: steps.map((step) => {
      const id = step.node_id || step.step_id
      const point = layout.node(id) || { x: 126, y: 50 }
      const title = step.description || `${step.tool_id}.${step.action}`
      const color =
        (
          { completed: '#22a06b', failed: '#dc4545', running: '#5268e5', waiting_user: '#d59a23', blocked: '#d59a23' } as Record<
            string,
            string
          >
        )[step.status || ''] || '#cbd5e1'
      return {
        id,
        type: 'default',
        position: { x: point.x - 126, y: point.y - 50 },
        sourcePosition: 'right',
        targetPosition: 'left',
        label: `${title.length > 42 ? `${title.slice(0, 42)}…` : title}\n${taskStatusLabel(step.status)}`,
        style: { borderColor: color },
        data: { step },
      }
    }),
    edges,
  }
}

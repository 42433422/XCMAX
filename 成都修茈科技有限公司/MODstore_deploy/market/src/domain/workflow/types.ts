/**
 * Workflow 编辑器领域类型。
 *
 * 来源：modstore_server/workflow_engine.py 中 Workflow / WorkflowNode / WorkflowEdge
 *      与 market/src/views/workflow/v2/composables/useWorkflowGraph.ts 中编辑态形状。
 *
 * 这里只放「跨视图共享、与后端 DTO 对齐」的形状；编辑器内部的特殊扩展（例如 Vue Flow
 * 渲染器属性）仍保留在 useWorkflowGraph.ts，以避免在 domain 层引入第三方类型依赖。
 */

import type { NodeKind } from './nodeKinds'

export interface BackendWorkflowMeta {
  id: number
  name: string
  description?: string
  is_active?: boolean
}

export interface BackendWorkflowNode {
  id: number
  node_type: string
  name: string
  config: Record<string, unknown>
  position_x: number
  position_y: number
}

export interface BackendWorkflowEdge {
  id: number
  source_node_id: number
  target_node_id: number
  condition: string
}

export interface BackendWorkflowGraph extends BackendWorkflowMeta {
  nodes: BackendWorkflowNode[]
  edges: BackendWorkflowEdge[]
}

/**
 * Vue Flow 编辑器中的 node.data；id 为 string（Vue Flow 要求）。
 */
export interface WorkflowFlowNodeData {
  kind: NodeKind
  label: string
  config: Record<string, unknown>
  /** 后端真实 id；未保存到后端时为 0 */
  backendId: number
}

export interface WorkflowFlowNode {
  id: string
  type: string
  position: { x: number; y: number }
  data: WorkflowFlowNodeData
}

export interface WorkflowFlowEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string | null
  type?: string
  label?: string
  data: { condition: string; backendId: number }
}

/**
 * 旧版占位符，部分应用层 API 仍引用；新代码应使用 `BackendWorkflowGraph`。
 */
export interface WorkflowGraph extends BackendWorkflowMeta {
  nodes?: BackendWorkflowNode[]
  edges?: BackendWorkflowEdge[]
}

/** WorkflowView 拆分共用的行数据结构（自 WorkflowView.vue 原样迁移） */

export interface WorkflowRow {
  id: number
  name?: string
  description?: string
  is_active?: boolean
  created_at?: string
  updated_at?: string
}

export interface EmployeeRow {
  id: number | string
  name?: string
  [key: string]: unknown
}

export interface WorkflowNodeRow {
  id: number
  workflow_id?: number
  name?: string
  node_type?: string
  config?: Record<string, unknown>
  position_x: number
  position_y: number
}

export interface WorkflowEdgeRow {
  id: number
  source_node_id?: number
  target_node_id?: number
  condition?: string | null
}

export interface ExecutionRow {
  id: number
  workflow_id?: number
  status?: string
  started_at?: string
  completed_at?: string
  error_message?: string
  output_data?: unknown
}

export interface TriggerRow {
  id: number
  workflow_id?: number
  trigger_type?: string
  trigger_key?: string
  is_active?: boolean
  config?: Record<string, unknown>
}

export interface RealPrecheck {
  ok?: boolean
  checkedCount?: number
  missingConfigCount?: number
  statusErrorCount?: number
  issues?: unknown[]
  nodeIds?: number[]
}

export interface WorkflowDetailResponse {
  nodes?: WorkflowNodeRow[]
}

/**
 * 工作流节点类型枚举与元数据形状。
 *
 * 与后端 WorkflowNode.node_type（modstore_server/models.py）对齐。
 * 这些纯类型定义放在 domain 层，避免 domain/workflow/types.ts 依赖 views 层。
 * 编辑器实现（REGISTRY、getNodeMeta、listByCategory）保留在
 * views/workflow/v2/composables/useNodeRegistry.ts 中并从此处导入。
 */

export type NodeKind =
  | 'start'
  | 'end'
  | 'employee'
  | 'condition'
  | 'openapi_operation'
  | 'knowledge_search'
  | 'webhook_trigger'
  | 'cron_trigger'
  | 'variable_set'
  | 'eskill'
  | 'vibe_skill'
  | 'vibe_workflow'
  | 'http_request'
  | 'code_execute'
  | 'data_transform'
  | 'loop'
  | 'parallel'
  | 'sub_workflow'

export type NodeCategory = 'flow' | 'employee' | 'logic' | 'integration' | 'trigger' | 'data'

export interface FieldSchema {
  key: string
  label: string
  type: 'text' | 'textarea' | 'number' | 'switch' | 'select' | 'json' | 'employee-picker' | 'eskill-picker'
  placeholder?: string
  helper?: string
  options?: { label: string; value: string | number | boolean }[]
  required?: boolean
}

export interface NodeMeta {
  kind: NodeKind
  label: string
  category: NodeCategory
  description: string
  accent: string
  icon: string
  hasInput: boolean
  hasOutput: boolean
  /** condition 节点用 true/false 两个出 handle，其它默认单出 */
  branchOutputs?: boolean
  defaultConfig: Record<string, unknown>
  fields: FieldSchema[]
}

/**
 * 与 modstore_server/domain/analytics.py 中 dataclass + `to_dict` 完全对齐。
 */
export interface ExecutionMetrics {
  total: number
  success: number
  failed: number
  /** 百分比，0-100，按 `(success/total)*100` 计算 */
  success_rate: number
  total_tokens: number
  /** 平均时长（毫秒）；后端总会返回数值，无样本时为 0.0 */
  avg_duration_ms: number
}

export interface CommerceMetrics {
  total_spent: number
  purchase_count: number
  refund_count: number
  wallet_transaction_count: number
}

export interface CatalogMetrics {
  total_packages: number
  public_packages: number
  employee_packs: number
}

/**
 * 与 modstore_server/infrastructure/analytics_repository.py `dashboard_for_user` 中 `recent_executions` 行结构一致。
 */
export interface RecentExecution {
  id: number
  employee_id?: string | null
  task?: string | null
  status: string
  duration_ms?: number | null
  llm_tokens?: number | null
  created_at: string
}

export interface AnalyticsDashboard {
  execution: ExecutionMetrics
  commerce: CommerceMetrics
  catalog: CatalogMetrics
  /** 由 `to_dict` 派生的简化字段：{ total: round(commerce.total_spent, 2) } */
  spending: { total: number }
  recent_executions: RecentExecution[]
}

/**
 * Employee Pack manifest 模型，与 modstore_server.employee_pack_export 及
 * market/src/employeePackClientExport.ts 中 buildEmployeePackManifestFromV2 行为对齐。
 *
 * 兼容两种来源：
 *   - 旧版「Mod manifest 单条 workflow」导出
 *   - V2 配置（employee_config_v2）导出
 */

export interface EmployeeIdentity {
  id: string
  label: string
  capabilities: string[]
  /** V2 manifest 才会写入；引用后端 workflow.id */
  workflow_id?: number
}

export interface EmployeePackCommerce {
  industry?: string
  price?: number
}

export interface EmployeePackMetadata {
  exported_by?: string
  exported_at?: string
}

/** Optional pointer to deploy_topology.yaml components[].id — not a collaboration edge. */
export interface EmployeePackReleaseHints {
  component_id?: string
}

/** Optional pointers for ops/docs — never used for Duty Graph topology. */
export interface EmployeePackReferences {
  /** GitHub Actions workflow display name (workflow file `name:`). */
  ci_workflow?: string
}

export interface EmployeePackManifest {
  id: string
  name: string
  version: string
  author?: string
  description?: string
  artifact: 'employee_pack'
  scope: 'global' | 'host'
  dependencies?: Record<string, string>
  employee: EmployeeIdentity
  /** V2 导出时附带原始 workflow_employees 列表，便于二次回放 */
  workflow_employees?: unknown[]
  /** V2 导出时附带的完整 employee_config_v2 */
  employee_config_v2?: Record<string, unknown>
  commerce?: EmployeePackCommerce
  metadata?: EmployeePackMetadata
  /** Maps pack to infra component id in MODstore_deploy/orchestration/deploy_topology.yaml */
  release_hints?: EmployeePackReleaseHints
  /** Non-topology hints (CI workflow name, etc.); duty graph ignores these. */
  references?: EmployeePackReferences
}

/**
 * 商城列表里看到的 employee_pack 概览（与 catalog item 字段子集一致）。
 */
export interface EmployeePackSummary {
  id: string
  name: string
  version?: string
  description?: string
}

/** 对外保留旧名，避免历史调用点立刻改动 */
export type EmployeePack = EmployeePackSummary

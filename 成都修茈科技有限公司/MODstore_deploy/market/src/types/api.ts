/**
 * 核心 API DTO 定义。
 *
 * 目标：替换 `api.ts` 里大量的 `any` / `as any`，至少让支付、工作流、目录、
 * 退款这些关键路径的请求与响应有明确的类型签名。
 *
 * 命名约定：
 * - Request 类型 → `XxxInput`（前端传给后端的 body）
 * - Response 类型 → `XxxResult` / `XxxResponse`
 * - 富资源对象 → `Xxx`（CatalogItem / Order / Employee 等领域对象）
 */

// ---------------------------------------------------------------- generic

/** 后端通用结果包，带 `ok` 字段表示成功失败。 */
export interface ApiOkResult<T = unknown> {
  ok: true
  data?: T
  message?: string
  [extra: string]: unknown
}

export interface ApiErrorResult {
  ok: false
  message?: string
  code?: string
  detail?: unknown
  [extra: string]: unknown
}

export type ApiResult<T = unknown> = ApiOkResult<T> | ApiErrorResult

// ---------------------------------------------------------------- auth

export interface AuthTokenResponse {
  access_token?: string
  refresh_token?: string
  user?: AuthUser
  [extra: string]: unknown
}

export interface AuthUser {
  id: number | string
  username?: string
  email?: string
  is_admin?: boolean
  [extra: string]: unknown
}

// ---------------------------------------------------------------- payment

export type PayChannel = 'alipay' | 'wechat' | string

export interface PaymentCheckoutInput {
  plan_id?: string
  item_id?: number | string
  total_amount?: number | string
  subject?: string
  wallet_recharge?: boolean
  pay_channel?: PayChannel
  /** 微信选 native / jsapi / h5 等；可选 */
  pay_type?: string
}

/** 服务端 ``/api/payment/sign-checkout`` 返回，已包含签名信息。 */
export interface PaymentSignResponse {
  plan_id: string
  item_id: number
  total_amount: number
  subject: string
  wallet_recharge: boolean
  request_id: string
  timestamp: number
  signature: string
}

/** 拼装好的 checkout 请求体，与 java/python `payment_contract` 对齐。 */
export interface PaymentCheckoutBody extends PaymentSignResponse {
  pay_channel?: PayChannel
  pay_type?: string
}

export interface PaymentCheckoutResponse {
  ok: boolean
  /** 支付方式：``page`` / ``wap`` / ``precreate`` / ``wechat_native`` / ``jsapi`` 等 */
  type?: string
  redirect_url?: string
  order_id?: string
  out_trade_no?: string
  qr_code?: string
  message?: string
  [extra: string]: unknown
}

export interface PaymentOrder {
  out_trade_no: string
  status: string
  total_amount: number | string
  subject?: string
  user_id?: number
  item_id?: number
  plan_id?: string
  order_kind?: string
  fulfilled?: boolean
  paid_at?: string
  trade_no?: string
  [extra: string]: unknown
}

export interface RefundApplyResponse {
  ok: boolean
  refund_id?: number | string
  message?: string
  [extra: string]: unknown
}

// ---------------------------------------------------------------- catalog
// CatalogItem and related shapes are canonical in domain/catalog/types.ts.
// Re-export from there so types/api.ts consumers get the same definition.
export type { CatalogItem, CatalogDetail, CatalogListResponse as CatalogListResult } from '../domain/catalog/types'

export type CatalogArtifact = 'employee_pack' | 'workflow_template' | 'mod' | 'bundle' | 'surface' | string

// ---------------------------------------------------------------- workflow

export type WorkflowNodeType =
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

export interface WorkflowNode {
  id: number | string
  workflow_id?: number | string
  node_type: WorkflowNodeType
  name?: string
  config?: Record<string, unknown> | string
  position?: { x: number; y: number }
  [extra: string]: unknown
}

export interface WorkflowEdge {
  id: number | string
  workflow_id?: number | string
  source_node_id: number | string
  target_node_id: number | string
  condition?: string
  [extra: string]: unknown
}

export interface WorkflowDefinition {
  id: number | string
  name: string
  description?: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  [extra: string]: unknown
}

export interface WorkflowSandboxRequest {
  input?: Record<string, unknown>
  mock_employees?: boolean
  validate_only?: boolean
  user_id?: number
  [extra: string]: unknown
}

export interface WorkflowSandboxStep {
  order: number
  node_id: number | string
  node_type: string
  node_name?: string
  duration_ms: number
  input_snapshot?: unknown
  output_delta?: unknown
  edge_taken?: { edge_id: number; condition: string | null; matched: boolean } | null
  mock_employee?: boolean
  condition_branches?: unknown[]
}

export interface WorkflowSandboxResponse {
  ok: boolean
  validate_only: boolean
  errors: string[]
  warnings: string[]
  steps: WorkflowSandboxStep[]
  output: Record<string, unknown>
  phase?: string
}

// ---------------------------------------------------------------- employee

export interface Employee {
  id: number | string
  name?: string
  description?: string
  pack_id?: string
  is_active?: boolean
  config?: Record<string, unknown>
  [extra: string]: unknown
}

export interface EmployeeRunRequest {
  employee_id: number | string
  task: string
  input?: Record<string, unknown>
  user_id?: number
  [extra: string]: unknown
}

export interface EmployeeRunResponse {
  ok: boolean
  output?: unknown
  duration_ms?: number
  error?: string
  [extra: string]: unknown
}

// ---------------------------------------------------------------- script workflow

export interface ScriptWorkflowDraft {
  id?: number | string
  name?: string
  brief?: string
  schema_in?: Record<string, unknown>
  [extra: string]: unknown
}

// ---------------------------------------------------------------- admin

export interface AdminResearchSettings {
  enabled?: boolean
  provider?: string
  model?: string
  [extra: string]: unknown
}

export interface AdminVectorSettings {
  provider?: string
  model?: string
  dim?: number
  [extra: string]: unknown
}

export interface AdminUser {
  id: number | string
  username?: string
  email?: string
  is_admin?: boolean
  created_at?: string
  [extra: string]: unknown
}

export interface AdminWallet {
  user_id: number | string
  balance: number | string
  updated_at?: string
  [extra: string]: unknown
}

export interface AdminCatalogItem {
  id: number | string
  pkg_id?: string
  name: string
  artifact?: string
  is_public?: boolean
  compliance_status?: string
  [extra: string]: unknown
}

export interface CatalogComplaint {
  id: number | string
  catalog_item_id: number | string
  user_id: number | string
  complaint_type?: string
  reason?: string
  status?: string
  created_at?: string
  [extra: string]: unknown
}

// ---------------------------------------------------------------- workbench

export interface WorkbenchSessionRequest {
  brief?: string
  skill_id?: string
  mode?: string
  provider?: string
  model?: string
  [extra: string]: unknown
}

export interface WorkbenchSession {
  session_id: string
  status?: string
  brief?: string
  result?: unknown
  steps?: unknown[]
  created_at?: string
  [extra: string]: unknown
}

export interface WorkbenchResearchContextRequest {
  query: string
  provider?: string
  model?: string
  [extra: string]: unknown
}

// ---------------------------------------------------------------- openapi connectors

export interface OpenApiConnector {
  id: number | string
  name?: string
  base_url?: string
  description?: string
  auth_type?: string
  is_active?: boolean
  created_at?: string
  [extra: string]: unknown
}

export interface OpenApiConnectorOperation {
  operation_id: string
  method?: string
  path?: string
  summary?: string
  enabled?: boolean
  [extra: string]: unknown
}

export interface OpenApiConnectorImportPayload {
  name: string
  spec?: Record<string, unknown>
  spec_url?: string
  base_url?: string
  [extra: string]: unknown
}

export interface OpenApiLog {
  id: number | string
  connector_id: number | string
  operation_id?: string
  status?: number
  duration_ms?: number
  request?: unknown
  response?: unknown
  created_at?: string
  [extra: string]: unknown
}

// ---------------------------------------------------------------- customer service

export interface CustomerServiceMessage {
  role: 'user' | 'assistant' | string
  content: string
  created_at?: string
  [extra: string]: unknown
}

export interface CustomerServiceSession {
  id: number | string
  user_id?: number | string
  status?: string
  created_at?: string
  messages?: CustomerServiceMessage[]
  [extra: string]: unknown
}

export interface CustomerServiceTicket {
  id: number | string
  user_id?: number | string
  session_id?: number | string
  status?: string
  priority?: string
  subject?: string
  created_at?: string
  [extra: string]: unknown
}

export interface CustomerServiceAction {
  id: number | string
  ticket_id?: number | string
  action_type?: string
  performed_by?: string
  created_at?: string
  [extra: string]: unknown
}

export interface CustomerServiceStandard {
  id: number | string
  name: string
  content?: string
  category?: string
  is_active?: boolean
  [extra: string]: unknown
}

export interface CustomerServiceIntegration {
  id: number | string
  name: string
  platform?: string
  config?: Record<string, unknown>
  is_active?: boolean
  [extra: string]: unknown
}

// ---------------------------------------------------------------- developer portal

export interface DeveloperToken {
  id: number | string
  name: string
  scopes?: string[]
  expires_at?: string | null
  created_at?: string
  last_used_at?: string | null
  [extra: string]: unknown
}

export interface DeveloperWebhook {
  id: number | string
  name: string
  target_url: string
  is_active?: boolean
  enabled_events?: string[]
  description?: string
  secret?: string
  created_at?: string
  [extra: string]: unknown
}

export interface WebhookDelivery {
  id: number | string
  webhook_id: number | string
  event_name?: string
  status?: string
  response_status?: number
  duration_ms?: number
  created_at?: string
  [extra: string]: unknown
}

// ---------------------------------------------------------------- notification

export interface Notification {
  id: number | string
  user_id?: number | string
  notification_type?: string
  title?: string
  content?: string
  is_read?: boolean
  created_at?: string
  data?: Record<string, unknown>
  [extra: string]: unknown
}

// ---------------------------------------------------------------- template

export interface WorkflowTemplate {
  id: number | string
  name: string
  description?: string
  template_category?: string
  template_difficulty?: string
  price?: number
  is_public?: boolean
  industry?: string
  preview_image_url?: string
  created_at?: string
  [extra: string]: unknown
}

// ---------------------------------------------------------------- analytics

export interface AnalyticsDashboardResponse {
  executions?: {
    total: number
    success: number
    failed: number
    avg_duration_ms?: number
  }
  commerce?: {
    total_revenue?: number
    order_count?: number
    refund_count?: number
  }
  [extra: string]: unknown
}


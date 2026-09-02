/**
 * AdminDutyEmployeeGraph 的领域类型定义（由入口组件原文机械迁出）。
 */
import type { Ref } from 'vue'

/** 解包 Ref/ComputedRef 为值类型（供拆分后的子组件 props 类型使用）。 */
export type Deref<T> = T extends Ref<infer V> ? V : T

export type EmpRow   = { id: string; name?: string; source?: 'catalog' | 'v1_catalog' | 'virtual'; industry?: string }

export type HealthSt = { total: number; success: number; rate: number; lastExecution?: string | null }

export type HealthLv = 'healthy' | 'warn' | 'idle' | 'unknown'

export type GapState = 'deployed' | 'missing' | 'untracked'

export type ViewMode = 'hub' | 'department' | 'legacy-area' | 'client'


export type LlmProviderSt = { provider: string; label: string; has_platform_key: boolean; has_user_override: boolean }

export type EmpLlmCfg = {
  provider: string        // e.g. "deepseek"
  model: string           // e.g. "deepseek-chat"
  handlers: string[]      // e.g. ["llm_md", "echo"]
  needsLlm: boolean       // false when handlers is echo-only
  activated: boolean      // true when provider has any key
  keySource: 'platform' | 'byok' | 'none' | 'auto'
}

export type LlmActLv = 'activated' | 'no_key' | 'echo_only' | 'unknown'


export type ExecRow = {
  id: number
  user_id: number
  task: string
  status: string
  duration_ms: number
  llm_tokens: number
  error: string
  created_at: string | null
}


export type CapRiskDetail = {
  handler: string
  reason?: string
  command_id?: string
  requires_approval?: boolean
}


export type EmpCapability = {
  employee_id: string
  name: string
  source: string
  deployed: boolean
  executable: boolean
  reasons: string[]
  handlers: string[]
  declared_dependencies: string[]
  llm: {
    provider: string
    model: string
    needs_llm: boolean
    activated: boolean
    key_source: string
  }
  risk: {
    high_risk: boolean
    requires_confirmation: boolean
    details: CapRiskDetail[]
  }
  recent_execution: {
    id: number
    status: string
    task: string
    duration_ms: number
    llm_tokens: number
    error: string
    created_at: string | null
  } | null
  recent_ops_audits: Array<{
    id: number
    handler: string
    command_id: string
    exit_code: number | null
    dry_run: boolean
    approval_required: boolean
    created_at: string | null
  }>
}


export type RunNodeStatus = 'idle' | 'pending' | 'running' | 'success' | 'failed' | 'skipped'


export type DutyGraphRunNode = {
  id: number
  employee_id: string
  order_index: number
  depends_on: string[]
  status: RunNodeStatus
  started_at: string | null
  completed_at: string | null
  duration_ms: number
  llm_tokens: number
  metric_id: number | null
  summary: string
  error: string
  result: Record<string, unknown>
}


export type DutyGraphRun = {
  id: number
  target_employee_id: string
  task: string
  input_data: Record<string, unknown>
  include_dependencies: boolean
  max_concurrency: number
  allow_high_risk_real_run: boolean
  status: string
  total_nodes: number
  success_count: number
  failed_count: number
  skipped_count: number
  error: string
  created_at: string | null
  started_at: string | null
  completed_at: string | null
  nodes: DutyGraphRunNode[]
}


export type NoKeyRow = {
  pkg_id: string
  name: string
  current_provider: string
  current_model: string
  key_source: string
  suggested_action: 'align_to_auto' | 'add_account_key'
  reasons: string[]
}

export type NoKeyResponse = {
  items: NoKeyRow[]
  count: number
  fernet_configured: boolean
  any_provider_has_key: boolean
}

export type AllHandsEmployeeRow = {
  employee_id: string
  name: string
  area: string
  status: string
  report_markdown: string
  cognition_error: string
  warnings: string[]
  manifest_signals: {
    name: string
    persona: string
    expertise: string[]
    handlers: string[]
    depends_on: string[]
    skills: { name: string; brief: string; kind: string }[]
    workflow_id: number
  }
  recent_failures: {
    id: number
    task: string
    status: string
    error: string
    duration_ms: number
    llm_tokens: number
    created_at: string | null
  }[]
  research_sources: { title: string; url: string }[]
  duration_ms?: number
  llm_tokens?: number
}

export type AllHandsSynthesizedAnswer = {
  question: string
  markdown: string
  cited_employees: string[]
  generated_at: string
  model: string
  error?: string
}

export type AllHandsReport = {
  ok: boolean
  error?: string
  started_at: string
  completed_at: string
  employees: AllHandsEmployeeRow[]
  summary: {
    total?: number
    ok?: number
    error?: number
    with_research?: boolean
    bench_provider?: string
    bench_model?: string
    user_question?: string
    synthesized?: boolean
  }
  synthesized_answer?: AllHandsSynthesizedAnswer | null
}

export type AllHandsProgress = {
  stage: string
  total: number
  completed: number
  ok: number
  error: number
  percent: number
  current_employee_id: string
  current_employee_name: string
  current_employee_status: string
  updated_at: string
}

export type AllHandsSessionSnapshot = {
  status: string
  error?: string | null
  artifact?: Record<string, unknown> | null
  planning_record?: {
    progress?: Partial<AllHandsProgress> | null
  } | null
}

export type MeetingMinutesBlock = {
  text?: string
  generated_at?: string
  model?: string
  error?: string
}

export type MeetingMinutesEmailMeta = {
  recipients_count?: number
  any_delivered?: boolean
  per_to?: { to: string; delivered: boolean; mode: string }[]
  skipped_reason?: string
}

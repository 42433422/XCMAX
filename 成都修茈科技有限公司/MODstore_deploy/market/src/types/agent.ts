// =====================================================================
// AI 数字管家 — 类型定义
// =====================================================================

/** 技能权限等级 */
export type SkillPermission = 'read' | 'suggest' | 'execute' | 'full'

/** 操作风险级别 */
export type ActionRisk = 'low' | 'medium' | 'high'

/** 确认策略 */
export type ConfirmStrategy = 'auto' | 'preview' | 'explicit'

/** 管家状态机 */
export type ButlerMode =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'operating'
  | 'awaiting_confirm'
  | 'speaking'
  | 'orchestrating'
  | 'error'

// ─── Orchestration ────────────────────────────────────────────────────
export interface StructuredStepMessage {
  summary?: string
  detail?: string
  warnings?: string[]
  skipped_reason?: string
  current_tool?: string
  todos?: Array<{ id: string; content: string; status: string }>
  slow_hint?: string
}

export interface OrchestrationStep {
  id: string
  label: string
  status: 'pending' | 'running' | 'done' | 'error' | 'skipped'
  message: string | StructuredStepMessage | null
  started_at?: string | null
}

export interface OrchestrationSession {
  sessionId: string
  steps: OrchestrationStep[]
  status: 'running' | 'done' | 'error'
  error?: string | null
  artifact?: Record<string, unknown> | null
}

// ─── 消息 ─────────────────────────────────────────────────────────────
export type AgentMessageRole = 'user' | 'assistant' | 'tool_call' | 'action_preview' | 'system'

export interface ToolCallPayload {
  name: string
  args: Record<string, unknown>
}

export interface ActionPreviewPayload {
  action: string
  label: string
  risk: ActionRisk
  args: Record<string, unknown>
}

export interface AgentMessage {
  id: string
  role: AgentMessageRole
  content: string
  /** 仅 role=tool_call 时有值 */
  toolCall?: ToolCallPayload
  /** 仅 role=action_preview 时有值 */
  actionPreview?: ActionPreviewPayload
  timestamp: number
  isLoading?: boolean
}

// ─── 技能 ─────────────────────────────────────────────────────────────
export interface AgentContext {
  route: string
  pageTitle: string
  pageSummary: string
  userMessage: string
  history: AgentMessage[]
  userId?: number
  membership?: string
}

export interface SkillResult {
  success: boolean
  message: string
  /** 可选的后续消息注入管家对话 */
  assistantReply?: string
}

export interface AgentSkill {
  id: string
  name: string
  description: string
  version: string
  trigger: {
    keywords?: string[]
    intent?: string[]
    /** 路由前缀匹配 */
    context?: string[]
  }
  execute: (context: AgentContext, args?: Record<string, unknown>) => Promise<SkillResult>
  permission: SkillPermission
  metadata: {
    author: string
    created_at: number
    evolution_count: number
    usage_count: number
  }
}

// ─── 动作 ─────────────────────────────────────────────────────────────
export interface ActionPermission {
  action: string
  risk: ActionRisk
  confirmStrategy: ConfirmStrategy
  confirmMessage: string
}

export interface PendingAction {
  id: string
  action: string
  label: string
  risk: ActionRisk
  args: Record<string, unknown>
  resolve: (confirmed: boolean) => void
}

// ─── Tool call (LLM 返回) ─────────────────────────────────────────────
export interface LLMToolCall {
  id: string
  name: string
  args: Record<string, unknown>
}

export interface LLMResponse {
  text: string
  tool_calls?: LLMToolCall[]
  conversation_id?: number
  charge_amount?: number
}

// ─── E-Skill ──────────────────────────────────────────────────────────
export interface ESkillDef {
  id: number
  skill_id: string
  name: string
  description: string
  version: string
  kind: string
  trigger_keywords: string[]
  trigger_intent: string[]
  permission: SkillPermission
  code: string
  is_active: boolean
  usage_count: number
  created_at: string
}

// ─── Phase 5 预留（接口只定义，不实现）──────────────────────────────────
export interface EvolutionNeed {
  id: string
  description: string
  observedCount: number
  exampleMessages: string[]
  detectedAt: number
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export interface EvolutionEngine {
  detectMissingCapability(): Promise<EvolutionNeed>
  generateSkillCode(need: EvolutionNeed): Promise<string>
  testGeneratedSkill(code: string): Promise<{ passed: boolean; errors: string[] }>
  reviewSkill(code: string): Promise<{ approved: boolean; notes: string }>
  registerSkill(code: string): Promise<void>
}
// TODO: evolution endpoint — 进化引擎暂不实现，等 Phase 5 启动时补充

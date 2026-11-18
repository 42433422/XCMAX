/** 聊天 UI 层消息（localStorage / 组件展示；role 用 ai 而非 API 的 assistant） */
import type { AgentRunTraceData } from '@/utils/agentRunTraceModel'
import type { AgentStepView } from '@/utils/agentStepChain'
import type { ChatTraceItem } from '@/composables/chat-orchestration/chatOrchestrationShared'
import type { ChatModelRoute } from '@/utils/chatModelRoute'
import type { ChatStatus } from 'ai'

export interface ChatExecutionProgressItem {
  phase: string
  label: string
  status: 'running' | 'success' | 'retrying' | 'waiting' | 'failed' | 'cancelled'
  at: string
}

export interface ChatApprovalCard {
  id?: string
  version?: number
  kind?: string
  plan_id?: string
  run_id?: string
  agent_run_id?: string
  intent?: string
  blocking_nodes?: string[]
  approval_required?: boolean
  approval_nodes?: Array<{ node_id?: string; tool_id?: string; action?: string }>
  approval_request_ids?: string[]
  approval_path?: string
  todo?: string[]
  reason?: string
  confirm_mode?: 'interactive' | 'approval' | string
  status?: 'pending' | 'confirmed' | 'cancelled'
  submitting?: boolean
  error?: string
}

export interface UiChatMessage {
  /** Local rendering identity, retained across cache reads and server reconciliation. */
  uiKey?: string
  role: 'user' | 'ai' | 'task'
  content: string
  time: string
  /** Request turn shared with server history; independent of local display text. */
  turnId?: string
  routeMetadata?: ChatModelRoute
  persistence?: {
    id: string
    status: 'local' | 'saving' | 'saved' | 'failed'
    localSaved?: boolean
    error?: string
    request?: { role: 'user' | 'ai' | 'task'; content: string; metadata?: string }
  }
  thinkingSteps?: string
  todoSteps?: string[]
  workflowAction?: string
  nodeResults?: Array<{
    node_id: string
    success: boolean
    tool_id: string
    action: string
    error?: string
    message?: string
    output_preview?: string
    retries?: number
    retryable?: boolean
    recovery_hint?: string
    duration_ms?: number
  }>
  contextSummary?: string
  streamingShell?: boolean
  /** 请求生命周期独立于正文是否已经开始输出；仅当前会话使用，不落库。 */
  streamStatus?: ChatStatus
  /** Heartbeat / idle copy while the shell is still waiting for visible text. */
  waitingHint?: string
  toolProgressLabel?: string
  /** Agent 执行时间线（计划-查询-执行 步骤），流式时实时更新，类似 Codex 对话 */
  executionProgress?: ChatExecutionProgressItem[]
  downloadUrl?: string
  /** 发货单文档下载链接（与右侧任务卡一致，便于在对话内直接下载） */
  shipmentDownloadUrl?: string
  /** 结构化工作流/审批确认卡片（Wave 2） */
  approvalCard?: ChatApprovalCard
  /** Agent 执行时间线（Codex 风格，由事件流构建） */
  agentRunTrace?: AgentRunTraceData
  /** 流式阶段的执行链步骤（tool_call 事件实时累积，不落库） */
  liveSteps?: AgentStepView[]
  /** 本轮附件工件取数轨迹（trace 事件，仅展示；历史消息允许为空） */
  trace?: ChatTraceItem[]
  /** 附件（Excel 分析等 Mod 回传的结构化数据） */
  attachments?: Record<string, unknown>[]
  /** XCAGI Business Harness 终态业务结果。 */
  businessResult?: Record<string, unknown>
  /** 后端命中语义缓存；对用户明确标注，避免把重复回答误解为新执行结果。 */
  sameAsPrevious?: boolean
  /** Intent versus a committed business write for this turn. */
  execution?: {
    idempotencyKey: string
    intent: string
    committed: boolean
    effect: 'none' | 'preview' | 'partial' | 'committed' | string
    /** 后端显式执行结论：未执行 / 部分成功 / 结果未知。 */
    outcome?: 'not_executed' | 'partial' | 'unknown' | 'succeeded' | string
    tenantId?: string
    customerCount?: number | null
    productCount?: number | null
  }
}

export type UiChatMessageExtras = Partial<UiChatMessage>

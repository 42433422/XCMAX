/** 聊天 UI 层消息（localStorage / 组件展示；role 用 ai 而非 API 的 assistant） */
import type { AgentRunTraceData } from '@/utils/agentRunTraceModel'

export interface ChatExecutionProgressItem {
  phase: string
  label: string
  status: 'running' | 'success' | 'retrying' | 'waiting' | 'failed' | 'cancelled'
  at: string
}

export interface ChatApprovalCard {
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
}

export interface ChatDecisionOption {
  id: string
  label: string
  description?: string
  message?: string
  composePrefill?: string
  recommended?: boolean
}

export interface UiChatMessage {
  role: 'user' | 'ai' | 'task'
  content: string
  time: string
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
  /** 附件（Excel 分析等 Mod 回传的结构化数据） */
  attachments?: Record<string, unknown>[]
  /** XCAGI Business Harness 终态业务结果。 */
  businessResult?: Record<string, unknown>
  /** AI 回复末尾的结构化对话选项；点击后仍通过正常对话链路处理。 */
  decisionOptions?: ChatDecisionOption[]
}

export type UiChatMessageExtras = Partial<UiChatMessage>

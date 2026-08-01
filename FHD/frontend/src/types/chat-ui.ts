/** 聊天 UI 层消息（localStorage / 组件展示；role 用 ai 而非 API 的 assistant） */

import type { AgentRunTraceData } from '@/utils/agentRunTraceModel'

export type { AgentRunTraceData }

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
  todo?: string[]
  reason?: string
  confirm_mode?: 'interactive' | 'approval' | string
  status?: 'pending' | 'confirmed' | 'cancelled'
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
  /** 每轮对话从接收、工具调用到完成/恢复的轻量执行时间线。 */
  executionProgress?: ChatExecutionProgressItem[]
  downloadUrl?: string
  /** 发货单文档下载链接（与右侧任务卡一致，便于在对话内直接下载） */
  shipmentDownloadUrl?: string
  /** 结构化工作流/审批确认卡片（Wave 2） */
  approvalCard?: ChatApprovalCard
  /** 附件（Excel 分析等 Mod 回传的结构化数据） */
  attachments?: Record<string, unknown>[]
}

export type UiChatMessageExtras = Partial<UiChatMessage>

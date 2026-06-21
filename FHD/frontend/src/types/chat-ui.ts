/** 聊天 UI 层消息（localStorage / 组件展示；role 用 ai 而非 API 的 assistant） */

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
  downloadUrl?: string
  /** 发货单文档下载链接（与右侧任务卡一致，便于在对话内直接下载） */
  shipmentDownloadUrl?: string
  /** 消息附件（持久化到 localStorage，结构由后端/工具决定） */
  attachments?: Array<Record<string, unknown>>
}

export type UiChatMessageExtras = Partial<UiChatMessage>

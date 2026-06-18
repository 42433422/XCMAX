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
  }>
  contextSummary?: unknown
  attachments?: Array<Record<string, unknown>>
  downloadUrl?: string
  toolProgressLabel?: string
  streamingShell?: boolean
  /** 发货单文档下载链接（与右侧任务卡一致，便于在对话内直接下载） */
  shipmentDownloadUrl?: string
}

export type UiChatMessageExtras = Partial<
  Pick<
    UiChatMessage,
    | 'attachments'
    | 'contextSummary'
    | 'downloadUrl'
    | 'shipmentDownloadUrl'
    | 'streamingShell'
    | 'thinkingSteps'
    | 'todoSteps'
    | 'toolProgressLabel'
    | 'workflowAction'
    | 'nodeResults'
  >
>

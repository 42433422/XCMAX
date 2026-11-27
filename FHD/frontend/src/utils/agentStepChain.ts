/**
 * 对话内「执行链」视图模型。
 *
 * 流式工具生命周期由 AI SDK 的 ToolUIPart 管理，此处只负责中文标签和展示投影。
 * 历史回执兼容 node_results；界面复用 shadcn-vue Trace。
 */
import { getToolName, isToolUIPart, type UIMessage } from 'ai'
import type { PlannerSseEvent } from '@/utils/chatSseStream'
import type { ExecutionObservation } from '@/api/agentRuns'
import { asRecord, asNonNegativeNumber } from '@/utils/typeGuards'
import { readExecutionObservation } from '@/utils/agentRunTraceModel'
import { actionDisplayName, toolActivityLabel, toolDisplayName } from '@/utils/toolLabels'

export type AgentStepState = 'pending' | 'running' | 'success' | 'failed' | 'waiting' | 'blocked' | 'unknown' | 'deferred' | 'partial'

export interface ChatNodeResultLike extends ExecutionObservation {
  node_id: string
  success: boolean
  tool_id: string
  action: string
  error?: string
  message?: string
  output_preview?: string
  retries?: number
  recovery_hint?: string
}

export interface AgentStepView extends ExecutionObservation {
  /** 稳定 key：优先使用 node_id */
  id: string
  toolId: string
  action: string
  title: string
  subtitle: string
  state: AgentStepState
  durationMs?: number
  output?: string
  error?: string
  hint?: string
  retries: number
  progress?: number
  processedRows?: number
  totalRows?: number
  /** 流式阶段由进度文案生成的临时步骤，完成后会被真实 node_results 替换 */
  live: boolean
}

const STATE_LABELS: Record<AgentStepState, string> = {
  pending: '待执行',
  running: '执行中',
  success: '已完成',
  failed: '失败',
  waiting: '待确认',
  blocked: '已阻断',
  unknown: '待核对',
  deferred: '待处理',
  partial: '部分完成',
}

const STATE_ICONS: Record<AgentStepState, string> = {
  pending: 'fa-circle-o',
  running: 'fa-circle-o-notch fa-spin',
  success: 'fa-check-circle',
  failed: 'fa-times-circle',
  waiting: 'fa-pause-circle',
  blocked: 'fa-ban',
  unknown: 'fa-question-circle',
  deferred: 'fa-clock-o',
  partial: 'fa-adjust',
}

export function stepStateLabel(state: AgentStepState): string {
  return STATE_LABELS[state] || state
}

export function stepStateIcon(state: AgentStepState): string {
  return STATE_ICONS[state] || 'fa-circle-o'
}

/** 把后端终态 node_results 映射为可展开的执行链步骤。 */
export function stepsFromNodeResults(rows: ChatNodeResultLike[] | undefined): AgentStepView[] {
  if (!Array.isArray(rows) || !rows.length) return []
  const steps: AgentStepView[] = []
  rows.forEach((row, index) => {
    if (!row) return
    const toolId = String(row.tool_id || '').trim()
    const action = String(row.action || '').trim()
    const error = String(row.error || '').trim()
    const state: AgentStepState = row.success ? 'success' : 'failed'
    steps.push({
      ...readExecutionObservation(row as unknown as Record<string, unknown>),
      id: String(row.node_id || '').trim() || `node-${index}`,
      toolId,
      action,
      title: toolActivityLabel(toolId, action, state) || toolDisplayName(toolId),
      subtitle: toolActivityLabel(toolId, action, state) ? '' : actionDisplayName(action),
      state,
      durationMs: asNonNegativeNumber(row.duration_ms),
      output: String(row.output_preview || '').trim() || undefined,
      error: error || (row.success ? undefined : String(row.message || '').trim() || undefined),
      hint: String(row.recovery_hint || '').trim() || undefined,
      retries: asNonNegativeNumber(row.retries) ?? 0,
      live: false,
    })
  })
  return steps
}

export type ToolCallEventLike = Omit<Extract<PlannerSseEvent, { type: 'tool_call' }>, 'type'>

/** 原生 SDK parts 的纯展示投影：不再维护第二套工具状态机。 */
export function stepsFromAiParts(parts: UIMessage['parts']): AgentStepView[] {
  const progress = new Map(parts.flatMap(part =>
    part.type === 'data-tool-progress' && part.id ? [[part.id, asRecord(part.data)] as const] : [],
  ))
  return parts.filter(isToolUIPart).map(part => {
    const detail = progress.get(part.toolCallId) || {}
    const name = getToolName(part)
    const separator = name.lastIndexOf('.')
    const toolId = String(detail.tool_id || (separator < 0 ? name : name.slice(0, separator)))
    const action = String(detail.action || (separator < 0 ? '' : name.slice(separator + 1)))
    let state: AgentStepState = part.state === 'output-available' ? 'success'
      : part.state === 'output-error' ? 'failed'
        : part.state === 'output-denied' ? 'blocked'
          : part.state === 'approval-requested' ? 'waiting'
            : part.state === 'approval-responded' && !part.approval.approved ? 'blocked' : 'running'
    if (state === 'success' || state === 'failed') {
      if (detail.requires_reconciliation === true) state = 'unknown'
      else if (detail.deferred === true) state = detail.committed === true ? 'partial' : 'deferred'
      else if (state === 'failed' && detail.committed === true) state = 'partial'
    }
    const error = part.state === 'output-error' ? part.errorText : undefined
    const preview = (state === 'partial' || state === 'unknown') && typeof detail.output_preview === 'string'
      ? detail.output_preview : undefined
    const percent = detail.progress
    return {
      ...readExecutionObservation(detail),
      id: part.toolCallId, toolId, action,
      title: toolActivityLabel(toolId, action, state) || toolDisplayName(toolId),
      subtitle: toolActivityLabel(toolId, action, state) ? '' : actionDisplayName(action), state,
      durationMs: asNonNegativeNumber(detail.duration_ms),
      output: typeof part.output === 'string' ? part.output : preview !== error ? preview : undefined,
      error,
      hint: String((state === 'running' ? detail.label : detail.recovery_hint) || '') || undefined,
      retries: asNonNegativeNumber(detail.retries) ?? 0,
      progress: typeof percent === 'number' && Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : undefined,
      processedRows: asNonNegativeNumber(detail.processed_rows), totalRows: asNonNegativeNumber(detail.total_rows),
      live: false,
    }
  })
}

/**
 * 模板库变更工具：完成事件需要让已挂载的模板库重新拉取列表，
 * 否则聊天里清理/删除后页面仍显示旧条目。
 */
export function isDocumentTemplateChange(ev: ToolCallEventLike | undefined): boolean {
  return ev?.phase === 'finished' && String(ev.tool_id || '').trim() === 'document_template'
}

export function chainState(steps: AgentStepView[]): AgentStepState {
  if (!steps.length) return 'pending'
  if (steps.some((step) => step.state === 'unknown')) return 'unknown'
  if (steps.some((step) => step.state === 'failed')) return 'failed'
  if (steps.some((step) => step.state === 'blocked')) return 'blocked'
  if (steps.some((step) => step.state === 'waiting')) return 'waiting'
  if (steps.some((step) => step.state === 'running' || step.state === 'pending')) return 'running'
  if (steps.some((step) => step.state === 'partial')) return 'partial'
  if (steps.some((step) => step.state === 'deferred')) return 'deferred'
  return 'success'
}

export function chainDurationMs(steps: AgentStepView[]): number | undefined {
  // This is tool time, not wall time: concurrent spans may overlap.
  if (!steps.length || steps.some(step => asNonNegativeNumber(step.durationMs) === undefined)) return undefined
  return asNonNegativeNumber(steps.reduce((sum, step) => sum + step.durationMs!, 0))
}

export function hasStepDetails(step: AgentStepView): boolean {
  return Boolean(step.output || step.error || step.hint || step.retries > 0 || step.trace_id || step.run_id || step.error_code)
}

export function formatStepDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`
}

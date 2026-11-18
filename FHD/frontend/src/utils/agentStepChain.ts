/**
 * 对话内「执行链」视图模型。
 *
 * 结构参照 Vercel AI Elements 的 Tool / Steps / Task 组件（ToolUIPart 状态机）：
 * pending → running → success / failed / waiting(需确认) / blocked。
 * 数据来源为后端终态 node_results，以及流式阶段的 tool_progress 文案占位。
 */
import { actionDisplayName, toolDisplayName } from '@/utils/toolLabels'

export type AgentStepState = 'pending' | 'running' | 'success' | 'failed' | 'waiting' | 'blocked'

export interface ChatNodeResultLike {
  node_id: string
  success: boolean
  tool_id: string
  action: string
  error?: string
  message?: string
  output_preview?: string
  retries?: number
  recovery_hint?: string
  duration_ms?: number
}

export interface AgentStepView {
  /** 稳定 key：优先 node_id，流式占位用 live-step */
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
}

const STATE_ICONS: Record<AgentStepState, string> = {
  pending: 'fa-circle-o',
  running: 'fa-circle-o-notch fa-spin',
  success: 'fa-check-circle',
  failed: 'fa-times-circle',
  waiting: 'fa-pause-circle',
  blocked: 'fa-ban',
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
      id: String(row.node_id || '').trim() || `node-${index}`,
      toolId,
      action,
      title: toolDisplayName(toolId),
      subtitle: actionDisplayName(action),
      state,
      durationMs: row.duration_ms && row.duration_ms > 0 ? row.duration_ms : undefined,
      output: String(row.output_preview || '').trim() || undefined,
      error: error || (row.success ? undefined : String(row.message || '').trim() || undefined),
      hint: String(row.recovery_hint || '').trim() || undefined,
      retries: Number(row.retries || 0),
      live: false,
    })
  })
  return steps
}

/** 流式阶段：用进度文案生成一个「当前正在执行」的占位步骤。 */
export function buildLiveStep(hint: string | undefined): AgentStepView | null {
  const text = String(hint || '').replace(/\s+/g, ' ').trim()
  if (!text) return null
  // 「正在调用工具: 搜索」这类文案去掉前缀，只留动作本身作为标题。
  const title = text.replace(/^正在(调用工具|执行|处理|查询|读取|写入|生成)[：:，,\s]*/u, '') || text
  return {
    id: 'live-step',
    toolId: '',
    action: '',
    title,
    subtitle: '',
    state: 'running',
    retries: 0,
    live: true,
  }
}

/**
 * 合并真实步骤与流式占位步骤。
 * 已有真实步骤时不再显示占位步骤，避免同一次执行出现两行。
 */
export function withLiveStep(steps: AgentStepView[], live: AgentStepView | null): AgentStepView[] {
  if (!steps.length) return live ? [live] : []
  if (!live) return steps
  const hasRunning = steps.some((step) => step.state === 'running' || step.state === 'waiting')
  return hasRunning ? steps : [...steps, live]
}

/** 后端流式 tool_call 事件（工具开始/结束）。 */
export interface ToolCallEventLike {
  phase?: 'started' | 'finished'
  node_id?: string
  tool_id?: string
  action?: string
  params?: Record<string, unknown>
  success?: boolean
  duration_ms?: number
  output_preview?: string
  error?: string
  retries?: number
  recovery_hint?: string
}

/**
 * 把一条 tool_call 事件合并进当前执行链。
 * `started` 生成/重置为执行中；`finished` 落到成功或失败，并按 node_id 原地更新。
 */
export function applyToolCallEvent(steps: AgentStepView[], ev: ToolCallEventLike | undefined): AgentStepView[] {
  if (!ev) return steps
  const nodeId = String(ev.node_id || '').trim()
  if (!nodeId) return steps
  const index = steps.findIndex((step) => step.id === nodeId)
  const base = index >= 0 ? steps[index] : undefined
  const toolId = String(ev.tool_id || base?.toolId || '').trim()
  const action = String(ev.action || base?.action || '').trim()
  const finished = ev.phase === 'finished'
  const next: AgentStepView = {
    id: nodeId,
    toolId,
    action,
    title: toolDisplayName(toolId),
    subtitle: actionDisplayName(action),
    state: finished ? (ev.success ? 'success' : 'failed') : 'running',
    durationMs: ev.duration_ms && ev.duration_ms > 0 ? ev.duration_ms : base?.durationMs,
    output: String(ev.output_preview || '').trim() || base?.output,
    error: finished && !ev.success ? String(ev.error || '').trim() || base?.error || '工具执行失败' : base?.error,
    hint: String(ev.recovery_hint || '').trim() || base?.hint,
    retries: Number(ev.retries ?? base?.retries ?? 0),
    live: false,
  }
  if (index < 0) return [...steps, next]
  const copy = steps.slice()
  copy[index] = next
  return copy
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
  if (steps.some((step) => step.state === 'failed')) return 'failed'
  if (steps.some((step) => step.state === 'blocked')) return 'blocked'
  if (steps.some((step) => step.state === 'waiting')) return 'waiting'
  if (steps.some((step) => step.state === 'running' || step.state === 'pending')) return 'running'
  return 'success'
}

export function chainDurationMs(steps: AgentStepView[]): number | undefined {
  const total = steps.reduce((sum, step) => sum + (step.durationMs || 0), 0)
  return total > 0 ? total : undefined
}

export function hasStepDetails(step: AgentStepView): boolean {
  return Boolean(step.output || step.error || step.hint || step.retries > 0)
}

export function formatStepDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`
}

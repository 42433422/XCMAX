/**
 * AgentRun 执行流可视化模型（Codex 风格）。
 *
 * 把后端 RunEvent[] 重建为按时间顺序排列的 Phase 列表，
 * 供 ChatMessageList 内联渲染为 terminal 风格执行流卡片。
 *
 * 重建规则（与 useAgentRunEvents.ts 的事件语义对齐）：
 * - planner.*        → PlannerPhase（思考/计划，灰色）
 * - tool.started     → 新建 ToolPhase（running 态）
 * - tool.completed   → 合并到对应 ToolPhase（success + output + duration）
 * - tool.failed      → 合并到对应 ToolPhase（failed + error + duration）
 * - observation.recorded → 挂到最近 ToolPhase 的 observations[]
 * - step.waiting_user     → 标记最近 ToolPhase 等待审批
 * - step.approved         → 取消等待审批
 * - step.retry_scheduled  → ToolPhase.retries++
 * - step.llm_repair_*     → 加入 repairHistory
 * - run.completed         → 终态 success
 * - run.failed / run.continue_ignored / budget.exceeded / planner.blocked → 终态 failed
 */

import type { AgentRunEvent, ExecutionObservation } from '@/api/agentRuns'
import { normalizeTaskDisplayText } from '@/utils/chatTaskLabels'
import { asString, asNonNegativeNumber, asRecord } from '@/utils/typeGuards'

export type TracePhaseKind = 'planner' | 'tool' | 'run'

export type TracePhaseStatus = 'running' | 'success' | 'failed' | 'waiting' | 'blocked' | 'paused' | 'cancelled'

export interface TraceBasePhase extends ExecutionObservation {
  kind: TracePhaseKind
  status: TracePhaseStatus
  /** 起始事件 id（用于折叠详情 key） */
  started_event_id: string
  /** ISO 时间戳 */
  started_at?: string
  error?: string
  /** 单行摘要（用于时间线主标题） */
  title: string
  /** 单行副标题（用于时间线副标题，可选） */
  subtitle?: string
  /** 折叠详情内容（markdown 文本） */
  detail?: string
}

export interface TracePlannerPhase extends TraceBasePhase {
  kind: 'planner'
  /** 计划生成的步骤数（若 planner.completed 事件 data 里有 step_count） */
  step_count?: number
}

export interface TraceToolPhase extends TraceBasePhase {
  kind: 'tool'
  /** 工具调用 node_id（用于合并同 step 事件） */
  node_id: string
  tool_id: string
  action: string
  /** 工具调用入参（JSON 字符串，用于折叠详情展示） */
  params_json?: string
  /** 输出摘要（成功时） */
  output_preview?: string
  /** 错误信息（失败时） */
  error?: string
  /** observation.recorded 事件追加的观察记录 */
  observations: string[]
  /** 是否在等待用户审批（step.waiting_user） */
  waiting_approval: boolean
  /** 重试次数（step.retry_scheduled 触发） */
  retries: number
  /** 修复历史（LLM 修复相关） */
  repair_history: string[]
}

export interface TraceRunPhase extends TraceBasePhase {
  kind: 'run'
  /** 最终输出（若 run.completed 的 data 里有 final_output） */
  final_output_preview?: string
}

export type TracePhase = TracePlannerPhase | TraceToolPhase | TraceRunPhase

export interface AgentRunTraceData extends ExecutionObservation {
  run_id: string
  /** 用户消息意图（取自 events data.intent 或 run_id 缩写） */
  intent: string
  /** 整体状态：running / success / failed / waiting */
  status: TracePhaseStatus
  /** 总耗时毫秒（完成态才有；running 时为已用时长大约值） */
  total_duration_ms?: number
  duration_scope?: string
  /** 按时间顺序的 phase 列表 */
  phases: TracePhase[]
  /** 末次更新的 event_id（用于增量同步判断） */
  last_event_id?: string
  /** 是否终态 */
  terminal: boolean
}

const TOOL_TERMINAL_FAILED = new Set<string>(['tool.failed'])

/** Keep only the shared observation contract, never arbitrary tool inputs. */
export function readExecutionObservation(data: Record<string, unknown>): ExecutionObservation {
  const result: ExecutionObservation = {}
  for (const key of ['trace_id', 'span_id', 'parent_span_id', 'request_id', 'task_id', 'run_id', 'step_id', 'node_id', 'call_id', 'error_code', 'error_type'] as const) {
    if (typeof data[key] === 'string' && data[key].trim()) result[key] = data[key].trim()
  }
  for (const key of ['duration_ms', 'attempt'] as const) {
    const value = asNonNegativeNumber(data[key])
    if (value !== undefined) result[key] = value
  }
  return result
}

export function executionObservationDetails(data: ExecutionObservation): string {
  return Object.entries(readExecutionObservation(data as Record<string, unknown>))
    .map(([key, value]) => `${key}: ${value}`).join('\n')
}

function pickString(data: Record<string, unknown>, ...keys: string[]): string {
  for (const k of keys) {
    const v = asString(data[k]).trim()
    if (v) return v
  }
  return ''
}

function pickNumber(data: Record<string, unknown>, ...keys: string[]): number | undefined {
  for (const k of keys) {
    const v = asNonNegativeNumber(data[k])
    if (v !== undefined) return v
  }
  return undefined
}

const GENERIC_TOOL_FAILURE = /(执行失败|工具调用失败|工具执行失败)$/

function toolFailureReason(data: Record<string, unknown>, message: unknown): string {
  // 后端事件标题常是「工具.动作 执行失败」这类通用文案，具体原因在 data.reason / data.error。
  const reason = asString(data.reason).trim() || asString(data.error).trim()
  const text = asString(message).trim()
  if (reason && (!text || GENERIC_TOOL_FAILURE.test(text))) return reason
  return text || reason || '工具执行失败'
}

function truncate(text: string, max: number): string {
  const s = text.trim()
  return s.length > max ? s.slice(0, max) + '…' : s
}

function safeParamsJson(data: Record<string, unknown>): string | undefined {
  const params = data.params ?? data.arguments ?? data.input
  if (params == null) return undefined
  if (typeof params === 'string') return params
  try {
    return JSON.stringify(params, null, 2)
  } catch {
    return undefined
  }
}

function safeOutputPreview(data: Record<string, unknown>): string | undefined {
  // legacy_chat_adapter 终态会塞整包 chat_payload，展示成 JSON 像乱码；只取可读摘要。
  if (data.chat_payload != null && data.output_preview == null && data.output == null) {
    const chat = asRecord(data.chat_payload)
    const nested = asRecord(chat.data)
    const text =
      asString(nested.text).trim() || asString(nested.response).trim() || asString(chat.response).trim() || asString(chat.message).trim()
    return text ? truncate(text, 240) : undefined
  }
  const raw = data.output_preview ?? data.output ?? data.result ?? data.message
  if (raw == null) return undefined
  if (typeof raw === 'string') return truncate(raw, 240)
  try {
    return truncate(JSON.stringify(raw), 240)
  } catch {
    return undefined
  }
}

/** 追踪通道内部文案：对办公用户无信息量，统一回落友好 fallback。 */
function isTracePlumbingTitle(text: string): boolean {
  return /进入\s*.*追踪|追踪完成|AgentRun|Legacy\s+planner/i.test(text)
}

function friendlyPhaseTitle(raw: unknown, fallback: string): string {
  const normalized = normalizeTaskDisplayText(raw)
  if (!normalized || isTracePlumbingTitle(normalized)) return fallback
  return normalized
}

function toolPhasesOf(trace: AgentRunTraceData): TraceToolPhase[] {
  return trace.phases.filter((p): p is TraceToolPhase => p.kind === 'tool')
}

/**
 * 气泡上不应展示的轨迹（答案正文为主）：
 * - 无工具（闲聊适配器假编排）
 * - 单次只读工具且无审批/重试/失败（如 customers.query）——完整「智能任务」剧场抢视线
 */
export function isTrivialChatTrace(trace: AgentRunTraceData | null | undefined): boolean {
  if (!trace || !trace.phases.length) return true
  const tools = toolPhasesOf(trace)
  if (tools.length === 0) return true
  if (tools.length > 1) return false
  if (trace.status !== 'success' && trace.status !== 'running') {
    return false
  }
  const t = tools[0]
  if (t.waiting_approval || t.retries > 0) return false
  if (t.status === 'failed' || t.status === 'blocked' || t.status === 'waiting') return false
  // 单工具成功或进行中：不挂气泡时间线 / 计划图
  return t.status === 'success' || t.status === 'running'
}

/** 执行计划图：仅多工具/复杂链路才有信息量；单工具默认不展示。 */
export function shouldShowAgentRunPlanGraph(trace: AgentRunTraceData | null | undefined): boolean {
  if (!trace || isTrivialChatTrace(trace)) return false
  return toolPhasesOf(trace).length >= 2
}

/**
 * 把 RunEvent[] 重建为 Codex 风格的 AgentRunTraceData。
 *
 * @param events 后端事件流（按时间顺序）
 * @param runId  AgentRun id
 */
export function buildAgentRunTraceFromEvents(events: AgentRunEvent[], runId: string): AgentRunTraceData {
  const list = Array.isArray(events) ? events : []
  const phases: TracePhase[] = []
  let intent = ''
  let status: TracePhaseStatus = 'running'
  let totalDurationMs: number | undefined
  let terminal = false
  let lastEventId: string | undefined
  let traceId: string | undefined
  let runObservation: ExecutionObservation = {}
  let durationScope: string | undefined
  const seenEvents = new Set<string>()

  /** 找最近一个未终态的 ToolPhase（用于合并同 step 事件） */
  function findToolPhase(nodeId: string, openOnly = true, identity?: ExecutionObservation): TraceToolPhase | undefined {
    for (let i = phases.length - 1; i >= 0; i -= 1) {
      const p = phases[i]
      if (p.kind !== 'tool') continue
      if (openOnly && (p.status === 'success' || p.status === 'failed')) continue
      if (nodeId && p.node_id !== nodeId) continue
      if (identity?.call_id && p.call_id && identity.call_id !== p.call_id) continue
      if (identity?.span_id && p.span_id && identity.span_id !== p.span_id) continue
      return p
    }
    return undefined
  }

  for (const ev of list) {
    if (ev.event_id && seenEvents.has(ev.event_id)) continue
    if (ev.event_id) seenEvents.add(ev.event_id)
    const type = asString(ev.event_type).trim() as AgentRunEvent['event_type']
    const data: Record<string, unknown> = { ...readExecutionObservation({ ...ev }), ...asRecord(ev.data) }
    const observation = readExecutionObservation({ ...ev, ...data })
    traceId ||= observation.trace_id
    if (type.startsWith('run.')) {
      runObservation = { ...runObservation, ...observation }
      if (type === 'run.completed' || (type === 'run.observed' && data.status === 'completed')) {
        delete runObservation.error_code
        delete runObservation.error_type
      }
    }
    if (!intent) intent = pickString(data, 'intent', 'user_message', 'message_text')
    if (ev.event_id) lastEventId = ev.event_id

    if (type === 'run.observed') {
      totalDurationMs = pickNumber(data, 'duration_ms') ?? totalDurationMs
      durationScope = pickString(data, 'duration_scope') || durationScope
      const observedStatus = pickString(data, 'status')
      const statuses: Record<string, TracePhaseStatus> = {
        queued: 'running', planning: 'running', running: 'running', retrying: 'running',
        completed: 'success', failed: 'failed', blocked: 'blocked', waiting_user: 'waiting',
        paused: 'paused', cancelled: 'cancelled', rejected: 'blocked',
      }
      if (statuses[observedStatus]) {
        status = statuses[observedStatus]
        terminal = ['completed', 'failed', 'cancelled', 'rejected'].includes(observedStatus)
      }
      const phase = [...phases].reverse().find(p => p.kind === (data.phase === 'planning' ? 'planner' : 'run'))
      const phaseDuration = asNonNegativeNumber(data.phase_duration_ms)
      if (phase && phaseDuration !== undefined && data.phase === 'planning') phase.duration_ms = phaseDuration
      if (terminal && phase?.kind === 'run' && phase.status === status && data.phase === 'execution') {
        phase.duration_ms = pickNumber(data, 'duration_ms')
      }
      if (terminal && status !== 'success' && !phases.some(p => p.kind === 'run' && p.status === status)) {
        phases.push({ ...observation, kind: 'run', status, started_event_id: asString(ev.event_id),
          title: status === 'cancelled' ? '任务已取消' : '执行已停止', error: pickString(data, 'error', 'message') || undefined })
      }
      continue
    }

    // PlannerPhase
    if (type === 'planner.started') {
      const openPlanner = [...phases].reverse().find((p) => p.kind === 'planner' && p.status === 'running') as TracePlannerPhase | undefined
      const title = friendlyPhaseTitle(ev.message, '正在生成执行计划')
      if (openPlanner) {
        Object.assign(openPlanner, observation)
        openPlanner.title = title
        openPlanner.started_event_id = asString(ev.event_id) || openPlanner.started_event_id
        openPlanner.started_at = asString(ev.created_at) || openPlanner.started_at
      } else {
        phases.push({
          ...observation,
          kind: 'planner',
          status: 'running',
          started_event_id: asString(ev.event_id),
          started_at: asString(ev.created_at),
          title,
        } as TracePlannerPhase)
      }
      status = 'running'
      continue
    }
    if (type === 'planner.completed') {
      const idx = [...phases].reverse().findIndex((p) => p.kind === 'planner')
      if (idx >= 0) {
        const realIdx = phases.length - 1 - idx
        const p = phases[realIdx] as TracePlannerPhase
        Object.assign(p, observation)
        p.status = 'success'
        p.duration_ms = pickNumber(data, 'duration_ms', 'planning_duration_ms')
        p.step_count = pickNumber(data, 'step_count', 'steps_count')
        p.title = '执行计划已生成'
        if (p.step_count) p.subtitle = `${p.step_count} 步`
      } else {
        phases.push({
          ...observation,
          kind: 'planner',
          status: 'success',
          started_event_id: asString(ev.event_id),
          started_at: asString(ev.created_at),
          duration_ms: pickNumber(data, 'duration_ms', 'planning_duration_ms'),
          step_count: pickNumber(data, 'step_count', 'steps_count'),
          title: '执行计划已生成',
          subtitle: pickNumber(data, 'step_count', 'steps_count') ? `${pickNumber(data, 'step_count', 'steps_count')} 步` : undefined,
        } as TracePlannerPhase)
      }
      status = 'running'
      continue
    }
    if (type === 'planner.blocked') {
      const idx = [...phases].reverse().findIndex((p) => p.kind === 'planner')
      if (idx >= 0) {
        const realIdx = phases.length - 1 - idx
        const p = phases[realIdx] as TracePlannerPhase
        Object.assign(p, observation)
        p.status = 'failed'
        p.detail = asString(ev.message).trim() || '计划生成被阻断'
      }
      status = 'failed'
      terminal = true
      continue
    }

    // ToolPhase
    if (type === 'tool.started') {
      const nodeId = pickString(data, 'node_id', 'step_id')
      const toolId = pickString(data, 'tool_id', 'tool')
      const action = pickString(data, 'action', 'name')
      phases.push({
        ...observation,
        kind: 'tool',
        status: 'running',
        started_event_id: asString(ev.event_id),
        started_at: asString(ev.created_at),
        node_id: nodeId,
        tool_id: toolId,
        action,
        title: toolId ? `工具调用 · ${toolId}` : '工具调用',
        subtitle: action || undefined,
        params_json: safeParamsJson(data),
        observations: [],
        waiting_approval: false,
        retries: 0,
        repair_history: [],
      } as TraceToolPhase)
      status = 'running'
      continue
    }
    if (type === 'tool.completed' || type === 'tool.failed') {
      const nodeId = pickString(data, 'node_id', 'step_id')
      const target = findToolPhase(nodeId, true, observation)
      const failed = TOOL_TERMINAL_FAILED.has(type)
      if (target) {
        Object.assign(target, observation)
        target.status = failed ? 'failed' : 'success'
        target.duration_ms = pickNumber(data, 'duration_ms')
        if (failed) {
          target.error = toolFailureReason(data, ev.message)
        } else {
          target.output_preview = safeOutputPreview(data)
        }
      } else {
        // 没找到对应 started，补一条紧凑 tool phase
        phases.push({
          ...observation,
          kind: 'tool',
          status: failed ? 'failed' : 'success',
          started_event_id: asString(ev.event_id),
          started_at: asString(ev.created_at),
          duration_ms: pickNumber(data, 'duration_ms'),
          node_id: nodeId,
          tool_id: pickString(data, 'tool_id', 'tool'),
          action: pickString(data, 'action', 'name'),
          title: pickString(data, 'tool_id', 'tool') || '工具调用',
          params_json: safeParamsJson(data),
          output_preview: failed ? undefined : safeOutputPreview(data),
          error: failed ? toolFailureReason(data, ev.message) : undefined,
          observations: [],
          waiting_approval: false,
          retries: 0,
          repair_history: [],
        } as TraceToolPhase)
      }
      continue
    }

    // Observation / step.*（挂到最近 ToolPhase）
    if (type === 'observation.recorded') {
      const target = findToolPhase(pickString(data, 'node_id', 'step_id'), false)
      const text = asString(ev.message).trim() || asString(data.observation).trim() || asString(data.summary).trim()
      if (target && text) target.observations.push(text)
      continue
    }
    if (type === 'step.waiting_user') {
      const target = findToolPhase(pickString(data, 'node_id', 'step_id'))
      if (target) {
        target.waiting_approval = true
        target.status = 'waiting'
      }
      status = 'waiting'
      continue
    }
    if (type === 'step.approved') {
      const target = findToolPhase(pickString(data, 'node_id', 'step_id'))
      if (target) {
        target.waiting_approval = false
        target.status = 'running'
      }
      status = 'running'
      continue
    }
    if (type === 'step.retry_scheduled') {
      const target = findToolPhase(pickString(data, 'node_id', 'step_id'), false)
      if (target) target.retries += 1
      continue
    }
    if (
      type === 'step.llm_repair_requested' ||
      type === 'step.llm_repair_failed' ||
      type === 'step.repair_applied' ||
      type === 'step.repair_rejected'
    ) {
      const target = findToolPhase(pickString(data, 'node_id', 'step_id'), false)
      const text = asString(ev.message).trim() || type
      if (target) target.repair_history.push(text)
      continue
    }
    if (type === 'step.blocked') {
      const target = findToolPhase(pickString(data, 'node_id', 'step_id'))
      if (target) {
        Object.assign(target, observation)
        target.status = 'blocked'
        target.error = asString(ev.message).trim() || '步骤依赖未满足'
      }
      status = 'failed'
      continue
    }

    // RunPhase（终态）
    if (type === 'run.completed') {
      status = 'success'
      terminal = true
      totalDurationMs = pickNumber(data, 'duration_ms', 'total_duration_ms') ?? totalDurationMs
      // chat_payload 的可读文本已在气泡正文渲染；再塞 final_output 会造成名单双份
      const finalPreview = data.chat_payload != null ? undefined : safeOutputPreview(data)
      phases.push({
        ...observation,
        kind: 'run',
        status: 'success',
        started_event_id: asString(ev.event_id),
        started_at: asString(ev.created_at),
        duration_ms: pickNumber(data, 'duration_ms', 'total_duration_ms'),
        title: friendlyPhaseTitle(ev.message, '执行完成'),
        final_output_preview: finalPreview,
      } as TraceRunPhase)
      continue
    }
    if (type === 'run.failed' || type === 'run.continue_ignored') {
      status = 'failed'
      terminal = true
      totalDurationMs = pickNumber(data, 'duration_ms', 'total_duration_ms') ?? totalDurationMs
      const failFallback = type === 'run.continue_ignored' ? '执行已中止' : '执行失败'
      phases.push({
        ...observation,
        kind: 'run',
        status: 'failed',
        started_event_id: asString(ev.event_id),
        started_at: asString(ev.created_at),
        duration_ms: totalDurationMs,
        title: friendlyPhaseTitle(ev.message, failFallback),
        error: friendlyPhaseTitle(ev.message, asString(data.error).trim() || failFallback),
        detail: asString(data.error).trim() || undefined,
      } as TraceRunPhase)
      continue
    }
    if (type === 'budget.exceeded') {
      status = 'failed'
      terminal = true
      phases.push({
        ...observation,
        kind: 'run',
        status: 'failed',
        started_event_id: asString(ev.event_id),
        started_at: asString(ev.created_at),
        title: '预算超限',
        error: asString(ev.message).trim() || 'AI 预算超限，执行已中止',
      } as TraceRunPhase)
      continue
    }
    if (type === 'run.created') {
      // 仅占位；随后 planner.started 会合并到同一 phase，避免「已创建 + 开始执行」双行噪音
      if (!phases.some((p) => p.kind === 'planner')) {
        phases.push({
          ...observation,
          kind: 'planner',
          status: 'running',
          started_event_id: asString(ev.event_id),
          started_at: asString(ev.created_at),
          title: friendlyPhaseTitle(ev.message, '智能任务已创建'),
        } as TracePlannerPhase)
      }
      continue
    }

    // 其余（llm/rag/memory/artifact/dataset/billing）不单独成 phase，避免噪音
  }

  // 终态后若仍有未关闭的 planner 占位（仅 run.created、无 started），收成成功/失败
  if (terminal) {
    for (const p of phases) {
      if (p.kind === 'planner' && p.status === 'running') {
        p.status = status
        if (!p.title || /已创建$/.test(p.title) || isTracePlumbingTitle(p.title)) {
          p.title = status === 'success' ? '执行计划已生成' : '计划未完成'
        }
      }
    }
  }

  return {
    ...runObservation,
    trace_id: runObservation.trace_id || traceId,
    run_id: runId,
    // 没有业务 intent 时不要拿 run_id 当标题（用户会看到 run_8a03… 像乱码）
    intent: intent || '',
    status,
    total_duration_ms: totalDurationMs,
    duration_scope: durationScope,
    phases,
    last_event_id: lastEventId,
    terminal,
  }
}

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

import type { AgentRunEvent } from '@/api/agentRuns'
import { asString, asNumber, asRecord } from '@/utils/typeGuards'

export type TracePhaseKind = 'planner' | 'tool' | 'run'

export type TracePhaseStatus =
  | 'running'
  | 'success'
  | 'failed'
  | 'waiting'
  | 'blocked'

export interface TraceBasePhase {
  kind: TracePhaseKind
  status: TracePhaseStatus
  /** 起始事件 id（用于折叠详情 key） */
  started_event_id: string
  /** ISO 时间戳 */
  started_at?: string
  /** 耗时毫秒（完成态才有） */
  duration_ms?: number
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

export interface AgentRunTraceData {
  run_id: string
  /** 用户消息意图（取自 events data.intent 或 run_id 缩写） */
  intent: string
  /** 整体状态：running / success / failed / waiting */
  status: TracePhaseStatus
  /** 总耗时毫秒（完成态才有；running 时为已用时长大约值） */
  total_duration_ms?: number
  /** 按时间顺序的 phase 列表 */
  phases: TracePhase[]
  /** 末次更新的 event_id（用于增量同步判断） */
  last_event_id?: string
  /** 是否终态 */
  terminal: boolean
}

const TOOL_TERMINAL_FAILED = new Set<string>(['tool.failed'])

function pickString(data: Record<string, unknown>, ...keys: string[]): string {
  for (const k of keys) {
    const v = asString(data[k]).trim()
    if (v) return v
  }
  return ''
}

function pickNumber(data: Record<string, unknown>, ...keys: string[]): number | undefined {
  for (const k of keys) {
    const v = asNumber(data[k], -1)
    if (v >= 0) return v
  }
  return undefined
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
  const raw =
    data.output_preview ??
    data.output ??
    data.result ??
    data.message
  if (raw == null) return undefined
  if (typeof raw === 'string') return truncate(raw, 240)
  try {
    return truncate(JSON.stringify(raw), 240)
  } catch {
    return undefined
  }
}

/**
 * 把 RunEvent[] 重建为 Codex 风格的 AgentRunTraceData。
 *
 * @param events 后端事件流（按时间顺序）
 * @param runId  AgentRun id
 */
export function buildAgentRunTraceFromEvents(
  events: AgentRunEvent[],
  runId: string,
): AgentRunTraceData {
  const list = Array.isArray(events) ? events : []
  const phases: TracePhase[] = []
  let intent = ''
  let status: TracePhaseStatus = 'running'
  let totalDurationMs: number | undefined
  let terminal = false
  let lastEventId: string | undefined

  /** 找最近一个未终态的 ToolPhase（用于合并同 step 事件） */
  function findOpenToolPhase(nodeId: string): TraceToolPhase | undefined {
    for (let i = phases.length - 1; i >= 0; i -= 1) {
      const p = phases[i]
      if (p.kind !== 'tool') continue
      if (p.status === 'success' || p.status === 'failed') continue
      if (nodeId && p.node_id && p.node_id !== nodeId) continue
      return p
    }
    return undefined
  }

  for (const ev of list) {
    const type = asString(ev.event_type).trim() as AgentRunEvent['event_type']
    const data = asRecord(ev.data)
    if (!intent) intent = pickString(data, 'intent', 'user_message', 'message_text')
    if (ev.event_id) lastEventId = ev.event_id

    // PlannerPhase
    if (type === 'planner.started') {
      phases.push({
        kind: 'planner',
        status: 'running',
        started_event_id: asString(ev.event_id),
        started_at: asString(ev.created_at),
        title: asString(ev.message).trim() || '正在生成执行计划',
      } as TracePlannerPhase)
      status = 'running'
      continue
    }
    if (type === 'planner.completed') {
      const idx = [...phases].reverse().findIndex((p) => p.kind === 'planner')
      if (idx >= 0) {
        const realIdx = phases.length - 1 - idx
        const p = phases[realIdx] as TracePlannerPhase
        p.status = 'success'
        p.duration_ms = pickNumber(data, 'duration_ms', 'planning_duration_ms')
        p.step_count = pickNumber(data, 'step_count', 'steps_count')
        p.title = '执行计划已生成'
        if (p.step_count) p.subtitle = `${p.step_count} 步`
      } else {
        phases.push({
          kind: 'planner',
          status: 'success',
          started_event_id: asString(ev.event_id),
          started_at: asString(ev.created_at),
          duration_ms: pickNumber(data, 'duration_ms', 'planning_duration_ms'),
          step_count: pickNumber(data, 'step_count', 'steps_count'),
          title: '执行计划已生成',
          subtitle: pickNumber(data, 'step_count', 'steps_count')
            ? `${pickNumber(data, 'step_count', 'steps_count')} 步`
            : undefined,
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
      const target = findOpenToolPhase(nodeId)
      const failed = TOOL_TERMINAL_FAILED.has(type)
      if (target) {
        target.status = failed ? 'failed' : 'success'
        target.duration_ms = pickNumber(data, 'duration_ms')
        if (failed) {
          target.error = asString(ev.message).trim() || asString(data.error).trim() || '工具执行失败'
        } else {
          target.output_preview = safeOutputPreview(data)
        }
      } else {
        // 没找到对应 started，补一条紧凑 tool phase
        phases.push({
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
          error: failed ? (asString(ev.message).trim() || asString(data.error).trim() || '工具执行失败') : undefined,
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
      const target = findOpenToolPhase('')
      const text = asString(ev.message).trim() || asString(data.observation).trim() || asString(data.summary).trim()
      if (target && text) target.observations.push(text)
      continue
    }
    if (type === 'step.waiting_user') {
      const target = findOpenToolPhase('')
      if (target) {
        target.waiting_approval = true
        target.status = 'waiting'
      }
      status = 'waiting'
      continue
    }
    if (type === 'step.approved') {
      const target = findOpenToolPhase('')
      if (target) {
        target.waiting_approval = false
        target.status = 'running'
      }
      status = 'running'
      continue
    }
    if (type === 'step.retry_scheduled') {
      const target = findOpenToolPhase('')
      if (target) target.retries += 1
      continue
    }
    if (
      type === 'step.llm_repair_requested' ||
      type === 'step.llm_repair_failed' ||
      type === 'step.repair_applied' ||
      type === 'step.repair_rejected'
    ) {
      const target = findOpenToolPhase('')
      const text = asString(ev.message).trim() || type
      if (target) target.repair_history.push(text)
      continue
    }
    if (type === 'step.blocked') {
      const target = findOpenToolPhase('')
      if (target) {
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
      totalDurationMs = pickNumber(data, 'duration_ms', 'total_duration_ms')
      phases.push({
        kind: 'run',
        status: 'success',
        started_event_id: asString(ev.event_id),
        started_at: asString(ev.created_at),
        duration_ms: totalDurationMs,
        title: asString(ev.message).trim() || '执行完成',
        final_output_preview: safeOutputPreview(data),
      } as TraceRunPhase)
      continue
    }
    if (type === 'run.failed' || type === 'run.continue_ignored') {
      status = 'failed'
      terminal = true
      totalDurationMs = pickNumber(data, 'duration_ms', 'total_duration_ms')
      phases.push({
        kind: 'run',
        status: 'failed',
        started_event_id: asString(ev.event_id),
        started_at: asString(ev.created_at),
        duration_ms: totalDurationMs,
        title: asString(ev.message).trim() || (type === 'run.continue_ignored' ? '执行已中止' : '执行失败'),
        error: asString(ev.message).trim() || asString(data.error).trim(),
        detail: asString(data.error).trim() || undefined,
      } as TraceRunPhase)
      continue
    }
    if (type === 'budget.exceeded') {
      status = 'failed'
      terminal = true
      phases.push({
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
      // 仅作为起点；若前面没 planner.started，加一个占位
      if (!phases.some((p) => p.kind === 'planner')) {
        phases.push({
          kind: 'planner',
          status: 'running',
          started_event_id: asString(ev.event_id),
          started_at: asString(ev.created_at),
          title: asString(ev.message).trim() || '智能任务已创建',
        } as TracePlannerPhase)
      }
      continue
    }

    // 其余（llm/rag/memory/artifact/dataset/billing）不单独成 phase，避免噪音
  }

  return {
    run_id: runId,
    intent: intent || truncate(runId, 12),
    status,
    total_duration_ms: totalDurationMs,
    phases,
    last_event_id: lastEventId,
    terminal,
  }
}

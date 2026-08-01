import type { AgentRunEvent } from '@/api/agentRuns'
import agentRunsApi from '@/api/agentRuns'
import type { TaskItem } from './useChatPersistence'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import { normalizeTaskDisplayText } from '@/utils/chatTaskLabels'
import {
  buildAgentRunTraceFromEvents,
  isTrivialChatTrace,
} from '@/utils/agentRunTraceModel'

type UpsertTask = (
  item: Partial<TaskItem> & { id: string; title: string; source: TaskItem['source']; type: string },
) => void

export interface UseAgentRunEventSyncOptions {
  upsertTask: UpsertTask
  getLastAiMessageRef?: () => string
}

const TERMINAL_EVENT_TYPES = new Set([
  'run.completed',
  'run.failed',
  'run.cancelled',
  'planner.blocked',
  'budget.exceeded',
])

export function extractAgentRunId(payload: unknown): string {
  const root = asRecord(payload)
  const data = asRecord(root.data)
  const rootAgentRun = asRecord(root.agent_run)
  const dataAgentRun = asRecord(data.agent_run)
  const run = asRecord(root.run || data.run)
  const candidates = [
    root.run_id,
    root.agent_run_id,
    data.run_id,
    data.agent_run_id,
    rootAgentRun.run_id,
    dataAgentRun.run_id,
    run.run_id,
  ]
  for (const raw of candidates) {
    const runId = asString(raw).trim()
    if (runId) return runId
  }
  return ''
}

function eventLabel(event: AgentRunEvent): string {
  const message = asString(event.message).trim()
  if (message) return normalizeTaskDisplayText(message)
  const type = asString(event.event_type).trim()
  const labels: Record<string, string> = {
    'run.created': '智能任务已创建',
    'planner.started': '正在生成执行计划',
    'planner.completed': '执行计划生成完成',
    'planner.blocked': '执行计划无法继续',
    'tool.started': '正在执行工具',
    'tool.completed': '工具执行完成',
    'tool.failed': '工具执行失败',
    'step.waiting_user': '等待用户确认',
    'step.blocked': '步骤依赖未满足',
    'run.completed': '智能任务执行完成',
    'run.failed': '智能任务执行失败',
    'run.cancelled': '智能任务已取消',
    'run.cancel_ignored': '任务已结束，无需重复取消',
    'run.continue_ignored': '当前没有等待确认的步骤',
    'budget.exceeded': '任务预算已超限',
  }
  return labels[type] || '执行状态已更新'
}

function statusFromEvents(events: AgentRunEvent[]): TaskItem['status'] {
  if (events.some((event) => event.event_type === 'run.completed')) return 'success'
  if (events.some((event) => event.event_type === 'run.cancelled')) return 'cancelled'
  if (events.some((event) => ['run.failed', 'tool.failed', 'planner.blocked', 'step.blocked', 'budget.exceeded'].includes(event.event_type))) {
    return 'failed'
  }
  if (events.some((event) => event.event_type === 'step.waiting_user')) return 'queued'
  return events.length ? 'running' : 'queued'
}

function progressFromEvents(events: AgentRunEvent[]): number {
  if (!events.length) return 5
  if (events.some((event) => event.event_type === 'run.completed')) return 100
  if (events.some((event) => event.event_type === 'run.cancelled')) return 100
  if (events.some((event) => ['run.failed', 'planner.blocked', 'budget.exceeded'].includes(event.event_type))) return 100
  if (events.some((event) => event.event_type === 'step.waiting_user')) return 85
  if (events.some((event) => event.event_type === 'tool.completed')) return 80
  if (events.some((event) => event.event_type === 'tool.started')) return 55
  if (events.some((event) => event.event_type === 'planner.completed')) return 35
  if (events.some((event) => event.event_type === 'planner.started')) return 15
  return 10
}

export function buildAgentRunTaskUpdate(params: {
  runId: string
  userText?: string
  events?: AgentRunEvent[]
  messageRef?: string
}): Partial<TaskItem> & { id: string; title: string; source: TaskItem['source']; type: string } {
  const events = asArray<AgentRunEvent>(params.events)
  const last = events[events.length - 1]
  const status = statusFromEvents(events)
  const stage = last ? eventLabel(last) : '等待执行状态'
  const errorEvent = [...events].reverse().find((event) =>
    ['run.failed', 'tool.failed', 'planner.blocked', 'step.blocked', 'budget.exceeded'].includes(event.event_type),
  )
  const userTitle = asString(params.userText).trim().slice(0, 30)
  return {
    id: `agent_${params.runId}`,
    type: 'agent_run',
    source: 'agent',
    title: `智能任务：${userTitle || params.runId}`,
    status,
    progress: progressFromEvents(events),
    stage,
    summary: status === 'success' ? '智能任务执行完成' : stage,
    error: errorEvent ? eventLabel(errorEvent) : '',
    messageRef: params.messageRef,
    payload: {
      agentRunId: params.runId,
      agentEvents: events,
      lastAgentEventId: asString(last?.event_id),
      terminal: status === 'success' || status === 'failed' || status === 'cancelled'
        || (last ? TERMINAL_EVENT_TYPES.has(last.event_type) : false),
    },
  }
}

export function useAgentRunEventSync(options: UseAgentRunEventSyncOptions) {
  const lastEventByRunId = new Map<string, string>()
  /** 累积 events（按 runId），保证流式轮询时 trace 不丢历史 */
  const eventsByRunId = new Map<string, AgentRunEvent[]>()
  const userTextByRunId = new Map<string, string>()
  const messageRefByRunId = new Map<string, string>()

  async function syncAgentRunEvents(runId: string, userText = ''): Promise<boolean> {
    const normalizedRunId = String(runId || '').trim()
    if (!normalizedRunId) return false
    const normalizedUserText = String(userText || '').trim()
    if (normalizedUserText) {
      userTextByRunId.set(normalizedRunId, normalizedUserText)
      const messageRef = options.getLastAiMessageRef?.() || ''
      if (messageRef) messageRefByRunId.set(normalizedRunId, messageRef)
    }
    const afterEventId = lastEventByRunId.get(normalizedRunId)
    try {
      const response = await agentRunsApi.listEvents(
        normalizedRunId,
        afterEventId ? { after_event_id: afterEventId } : {},
      )
      const fresh = Array.isArray(response?.data) ? response.data : []
      const accumulated = afterEventId
        ? [...(eventsByRunId.get(normalizedRunId) || []), ...fresh]
        : fresh
      if (accumulated.length) eventsByRunId.set(normalizedRunId, accumulated)
      const last = accumulated[accumulated.length - 1]
      if (last?.event_id) {
        lastEventByRunId.set(normalizedRunId, last.event_id)
      }
      if (!accumulated.length) return false
      // 闲聊无工具、或单次成功只读工具：不灌「智能任务」侧栏 / 气泡剧场
      const previewTrace = buildAgentRunTraceFromEvents(accumulated, normalizedRunId)
      if (isTrivialChatTrace(previewTrace) && previewTrace.terminal) return true
      const update = buildAgentRunTaskUpdate({
        runId: normalizedRunId,
        userText: userTextByRunId.get(normalizedRunId) || '',
        events: accumulated,
        messageRef: messageRefByRunId.get(normalizedRunId) || '',
      })
      options.upsertTask(update)
      return update.payload?.terminal === true
    } catch {
      const fallbackEvents = eventsByRunId.get(normalizedRunId) || []
      if (!fallbackEvents.length) return false
      const previewTrace = buildAgentRunTraceFromEvents(fallbackEvents, normalizedRunId)
      if (isTrivialChatTrace(previewTrace) && previewTrace.terminal) return true
      const update = buildAgentRunTaskUpdate({
        runId: normalizedRunId,
        userText: userTextByRunId.get(normalizedRunId) || '',
        events: fallbackEvents,
        messageRef: messageRefByRunId.get(normalizedRunId) || '',
      })
      options.upsertTask(update)
      return update.payload?.terminal === true
    }
  }

  async function syncAgentRunFromPayload(payload: unknown, userText = ''): Promise<void> {
    const runId = extractAgentRunId(payload)
    if (!runId) return
    await syncAgentRunEvents(runId, userText)
  }

  async function restoreRecentAgentRuns(userId: string, limit = 20): Promise<string[]> {
    const normalizedUserId = String(userId || '').trim()
    if (!normalizedUserId) return []
    const activeRunIds: string[] = []
    try {
      const response = await agentRunsApi.listRuns({ user_id: normalizedUserId, limit })
      const runs = Array.isArray(response?.data) ? response.data : []
      for (const run of runs) {
        const runId = asString(run?.run_id).trim()
        const events = asArray<AgentRunEvent>(run?.events)
        if (!runId || !events.length) continue
        const trace = buildAgentRunTraceFromEvents(events, runId)
        if (!trace.terminal) activeRunIds.push(runId)
        const restoredUserText = asString(run?.message).trim()
        if (restoredUserText) userTextByRunId.set(runId, restoredUserText)
        if (isTrivialChatTrace(trace) && trace.terminal) continue
        eventsByRunId.set(runId, events)
        const last = events[events.length - 1]
        if (last?.event_id) lastEventByRunId.set(runId, last.event_id)
        options.upsertTask(buildAgentRunTaskUpdate({
          runId,
          userText: asString(run?.message),
          events,
        }))
      }
      return activeRunIds
    } catch {
      // Task recovery is best effort; persisted chat remains available.
      return []
    }
  }

  return {
    syncAgentRunEvents,
    syncAgentRunFromPayload,
    restoreRecentAgentRuns,
  }
}

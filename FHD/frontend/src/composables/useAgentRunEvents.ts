import type { AgentRunEvent } from '@/api/agentRuns'
import agentRunsApi from '@/api/agentRuns'
import type { TaskItem } from './useChatPersistence'
import { asArray, asRecord, asString } from '@/utils/typeGuards'

type UpsertTask = (
  item: Partial<TaskItem> & { id: string; title: string; source: TaskItem['source']; type: string },
) => void

export interface UseAgentRunEventSyncOptions {
  upsertTask: UpsertTask
  getLastAiMessageRef?: () => string
}

const TERMINAL_EVENT_TYPES = new Set(['run.completed', 'run.failed', 'planner.blocked'])

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
  if (message) return message
  const type = asString(event.event_type).trim()
  const labels: Record<string, string> = {
    'run.created': 'Agent run 已创建',
    'planner.started': '正在生成 Agent 计划',
    'planner.completed': 'Agent 计划生成完成',
    'planner.blocked': 'Agent 计划被阻塞',
    'tool.started': '正在执行工具',
    'tool.completed': '工具执行完成',
    'tool.failed': '工具执行失败',
    'step.waiting_user': '等待用户确认',
    'step.blocked': '步骤依赖未满足',
    'run.completed': 'Agent run 执行完成',
    'run.failed': 'Agent run 失败',
  }
  return labels[type] || type || 'Agent run 更新'
}

function statusFromEvents(events: AgentRunEvent[]): TaskItem['status'] {
  if (events.some((event) => event.event_type === 'run.completed')) return 'success'
  if (events.some((event) => ['run.failed', 'tool.failed', 'planner.blocked', 'step.blocked'].includes(event.event_type))) {
    return 'failed'
  }
  if (events.some((event) => event.event_type === 'step.waiting_user')) return 'queued'
  return events.length ? 'running' : 'queued'
}

function progressFromEvents(events: AgentRunEvent[]): number {
  if (!events.length) return 5
  if (events.some((event) => event.event_type === 'run.completed')) return 100
  if (events.some((event) => ['run.failed', 'planner.blocked'].includes(event.event_type))) return 100
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
  const stage = last ? eventLabel(last) : '等待 Agent 事件'
  const errorEvent = [...events].reverse().find((event) =>
    ['run.failed', 'tool.failed', 'planner.blocked', 'step.blocked'].includes(event.event_type),
  )
  const userTitle = asString(params.userText).trim().slice(0, 30)
  return {
    id: `agent_${params.runId}`,
    type: 'agent_run',
    source: 'agent',
    title: `Agent 任务：${userTitle || params.runId}`,
    status,
    progress: progressFromEvents(events),
    stage,
    summary: status === 'success' ? 'Agent run 执行完成' : stage,
    error: errorEvent ? eventLabel(errorEvent) : '',
    messageRef: params.messageRef,
    payload: {
      agentRunId: params.runId,
      agentEvents: events,
      lastAgentEventId: asString(last?.event_id),
      terminal: last ? TERMINAL_EVENT_TYPES.has(last.event_type) : false,
    },
  }
}

export function useAgentRunEventSync(options: UseAgentRunEventSyncOptions) {
  const lastEventByRunId = new Map<string, string>()

  async function syncAgentRunEvents(runId: string, userText = ''): Promise<void> {
    const normalizedRunId = String(runId || '').trim()
    if (!normalizedRunId) return
    const afterEventId = lastEventByRunId.get(normalizedRunId)
    try {
      const response = await agentRunsApi.listEvents(
        normalizedRunId,
        afterEventId ? { after_event_id: afterEventId } : {},
      )
      const events = Array.isArray(response?.data) ? response.data : []
      if (!events.length) return
      const last = events[events.length - 1]
      if (last?.event_id) {
        lastEventByRunId.set(normalizedRunId, last.event_id)
      }
      options.upsertTask(buildAgentRunTaskUpdate({
        runId: normalizedRunId,
        userText,
        events,
        messageRef: options.getLastAiMessageRef?.() || '',
      }))
    } catch {
      options.upsertTask(buildAgentRunTaskUpdate({
        runId: normalizedRunId,
        userText,
        events: [],
        messageRef: options.getLastAiMessageRef?.() || '',
      }))
    }
  }

  async function syncAgentRunFromPayload(payload: unknown, userText = ''): Promise<void> {
    const runId = extractAgentRunId(payload)
    if (!runId) return
    await syncAgentRunEvents(runId, userText)
  }

  return {
    syncAgentRunEvents,
    syncAgentRunFromPayload,
  }
}

import type { AgentRun, AgentRunEvent } from '@/api/agentRuns'
import agentRunsApi from '@/api/agentRuns'
import type { TaskItem } from './useChatPersistence'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import { normalizeTaskDisplayText } from '@/utils/chatTaskLabels'
import { hasAgentRunExecutionEvidence, hasConfirmedAgentRunExecution } from '@/utils/agentRunExecution'
import { groupAgentRunsIntoTasks } from '@/utils/agentTaskWorkspaceModel'
import { bindPendingFirstAiTaskRun, completeFirstAiTaskFromRun } from '@/constants/productFlow'
import { resolveChatIdentity } from '@/utils/chatStorageKeys'

type UpsertTask = (item: Partial<TaskItem> & { id: string; title: string; source: TaskItem['source']; type: string }) => void

export interface UseAgentRunEventSyncOptions {
  upsertTask: UpsertTask
  removeTask?: (id: string) => void
  getLastAiMessageRef?: () => string
}

const TERMINAL_EVENT_TYPES = new Set(['run.completed', 'run.failed', 'planner.blocked'])

/** 视为「只读查询」的工具 action（答案优先，不创建任务面板行）。 */
const READONLY_QUERY_ACTIONS = new Set(['query', 'list', 'search', 'read', 'get', 'count'])

/** 会改动模板库的工具；对话里改完模板后，已打开的模板库页必须刷新。 */
const TEMPLATE_MUTATING_TOOLS = new Set(['document_template', 'elt_import', 'template_preview'])
const TEMPLATE_MUTATING_ACTIONS = new Set([
  'create',
  'update',
  'delete',
  'clear',
  'save',
  'import',
  'execute',
  'replace',
  'upload',
])

function isTemplateMutationEvent(event: AgentRunEvent): boolean {
  if (event.event_type !== 'tool.completed') return false
  const data = asRecord(event.data)
  const toolId = asString(data.tool_id).trim().toLowerCase()
  if (!TEMPLATE_MUTATING_TOOLS.has(toolId)) return false
  const action = asString(data.action).trim().toLowerCase()
  return !action || TEMPLATE_MUTATING_ACTIONS.has(action)
}

/**
 * 单次只读查询工具（如 customers.query）成功后，不创建「智能任务」任务面板行。
 * 与 agentRunTraceModel.isTrivialChatTrace 语义对齐：答案正文为主，避免剧场抢视线。
 */
function isTrivialReadOnlyQueryRun(events: AgentRunEvent[]): boolean {
  const toolStarted = events.filter((event) => event.event_type === 'tool.started')
  if (toolStarted.length !== 1) return false
  const data = asRecord(toolStarted[0].data)
  const action = asString(data.action).trim().toLowerCase()
  if (!READONLY_QUERY_ACTIONS.has(action)) return false
  const blocked = events.some((event) => ['tool.failed', 'step.blocked', 'step.waiting_user', 'planner.blocked'].includes(event.event_type))
  return !blocked
}

export function extractAgentRunId(payload: unknown): string {
  const root = asRecord(payload)
  const data = asRecord(root.data)
  const rootAgentRun = asRecord(root.agent_run)
  const dataAgentRun = asRecord(data.agent_run)
  const run = asRecord(root.run || data.run)
  const candidates = [root.run_id, root.agent_run_id, data.run_id, data.agent_run_id, rootAgentRun.run_id, dataAgentRun.run_id, run.run_id]
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
  }
  return labels[type] || '执行状态已更新'
}

function statusFromEvents(events: AgentRunEvent[]): TaskItem['status'] {
  if (events.some((event) => ['run.failed', 'tool.failed', 'planner.blocked', 'step.blocked'].includes(event.event_type))) {
    return 'failed'
  }
  if (events.some((event) => event.event_type === 'step.waiting_user')) return 'queued'
  if (events.some((event) => event.event_type === 'run.completed')) {
    return hasConfirmedAgentRunExecution(events) ? 'success' : 'failed'
  }
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
}): (Partial<TaskItem> & { id: string; title: string; source: TaskItem['source']; type: string }) | null {
  const events = asArray<AgentRunEvent>(params.events)
  if (!hasAgentRunExecutionEvidence(events)) return null
  if (isTrivialReadOnlyQueryRun(events)) return null
  const last = events[events.length - 1]
  const status = statusFromEvents(events)
  const unconfirmedCompletion =
    status === 'failed' && events.some((event) => event.event_type === 'run.completed') && !hasConfirmedAgentRunExecution(events)
  const stage = unconfirmedCompletion ? '未确认执行结果' : last ? eventLabel(last) : '等待执行状态'
  const errorEvent = [...events]
    .reverse()
    .find((event) => ['run.failed', 'tool.failed', 'planner.blocked', 'step.blocked'].includes(event.event_type))
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
    error: errorEvent ? eventLabel(errorEvent) : status === 'failed' ? '未收到可确认的工具执行结果' : '',
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
  const eventsByRunId = new Map<string, AgentRunEvent[]>()
  // 模板库页可能一直开着；对话里改了模板就通知它刷新一次，已通知过的事件不重复触发。
  const notifiedTemplateEvents = new Set<string>()
  let lastIdentity = ''

  function mergeEvents(runId: string, incoming: AgentRunEvent[]): AgentRunEvent[] {
    const known = eventsByRunId.get(runId) || []
    const seen = new Set(known.map((event) => asString(event.event_id).trim()).filter(Boolean))
    const merged = [...known]
    incoming.forEach((event) => {
      const eventId = asString(event.event_id).trim()
      if (eventId && seen.has(eventId)) return
      if (eventId) seen.add(eventId)
      merged.push(event)
    })
    eventsByRunId.set(runId, merged)
    return merged
  }

  function notifyTemplateMutation(incoming: AgentRunEvent[]): void {
    let changed = false
    for (const event of incoming) {
      if (!isTemplateMutationEvent(event)) continue
      const key = asString(event.event_id).trim() || `${event.event_type}:${event.message || ''}`
      if (notifiedTemplateEvents.has(key)) continue
      notifiedTemplateEvents.add(key)
      changed = true
    }
    if (changed && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('xcagi:templates-updated', { detail: { source: 'agent-run' } }))
    }
  }

  function syncTaskPanel(runId: string, userText: string, events: AgentRunEvent[], messageRef: string): void {
    const update = buildAgentRunTaskUpdate({
      runId,
      userText,
      events,
      messageRef,
    })
    if (update) options.upsertTask(update)
    else options.removeTask?.(`agent_${runId}`)
  }

  async function syncAgentRunEvents(runId: string, userText = '', isGenerationCurrent: () => boolean = () => true): Promise<void> {
    const identity = resolveChatIdentity()
    const messageRef = options.getLastAiMessageRef?.() || ''
    const isCurrent = () => isGenerationCurrent() && identity === resolveChatIdentity()
    if (lastIdentity !== identity) {
      lastEventByRunId.clear()
      eventsByRunId.clear()
      lastIdentity = identity
    }
    const normalizedRunId = String(runId || '').trim()
    if (!normalizedRunId) return
    const afterEventId = lastEventByRunId.get(normalizedRunId)
    try {
      const response = await agentRunsApi.listEvents(normalizedRunId, afterEventId ? { after_event_id: afterEventId } : {})
      if (!isCurrent()) return
      const incoming = Array.isArray(response?.data) ? response.data : []
      if (!incoming.length) return
      const events = mergeEvents(normalizedRunId, incoming)
      notifyTemplateMutation(incoming)
      const last = incoming[incoming.length - 1]
      if (last?.event_id) {
        lastEventByRunId.set(normalizedRunId, last.event_id)
      }
      let run: AgentRun | undefined
      try {
        const runResponse = await agentRunsApi.getRun(normalizedRunId)
        run = runResponse?.data
      } catch {
        // Older/offline runtimes may expose the event feed before the run detail route.
      }
      if (!isCurrent()) return
      const durableTask = run ? groupAgentRunsIntoTasks([{ ...run, events }])[0] : null
      if (run) completeFirstAiTaskFromRun(run)
      if (durableTask) {
        options.removeTask?.(`agent_${normalizedRunId}`)
        options.upsertTask({ ...durableTask, messageRef })
      } else {
        syncTaskPanel(normalizedRunId, userText, events, messageRef)
      }
    } catch {
      if (isCurrent()) options.removeTask?.(`agent_${normalizedRunId}`)
    }
  }

  async function syncAgentRunFromPayload(payload: unknown, userText = '', isCurrent: () => boolean = () => true): Promise<void> {
    const runId = extractAgentRunId(payload)
    if (!runId || !isCurrent()) return
    bindPendingFirstAiTaskRun(runId, userText)
    await syncAgentRunEvents(runId, userText, isCurrent)
  }

  return {
    syncAgentRunEvents,
    syncAgentRunFromPayload,
  }
}

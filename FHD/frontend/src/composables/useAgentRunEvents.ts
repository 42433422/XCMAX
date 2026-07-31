import type { AgentRun, AgentRunEvent } from '@/api/agentRuns'
import agentRunsApi from '@/api/agentRuns'
import type { TaskItem } from './useChatPersistence'
import {
  asArray,
  asNumber,
  asRecord,
  asString,
} from '@/utils/typeGuards'
import { normalizeTaskDisplayText } from '@/utils/chatTaskLabels'
import type {
  OrchestrationDatabase,
  OrchestrationChange,
  OrchestrationEmployee,
  OrchestrationEvidence,
  OrchestrationEvidenceKind,
  OrchestrationPrint,
  OrchestrationTraceStep,
  OrchestrationVerification,
} from '@/types/orchestration'

type UpsertTask = (
  item: Partial<TaskItem> & { id: string; title: string; source: TaskItem['source']; type: string },
) => void

export interface UseAgentRunEventSyncOptions {
  upsertTask: UpsertTask
  getTasks?: () => TaskItem[]
  getLastAiMessageRef?: () => string
  attachOrchestrationTrace?: (trace: OrchestrationTraceStep[]) => void
}

const TERMINAL_EVENT_TYPES = new Set([
  'run.completed',
  'run.failed',
  'run.cancelled',
  'planner.blocked',
])
const ACTIVE_RUN_STATUSES = new Set(['queued', 'planning', 'running', 'retrying'])

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
    'run.queued': '已进入后台队列',
    'run.background_started': '后台执行器已接管',
    'run.pause_requested': '正在暂停当前任务',
    'run.paused': '任务已暂停',
    'run.resumed': '任务已恢复',
    'run.cancel_requested': '正在取消当前任务',
    'run.cancelled': '任务已取消',
    'run.recovered': '已从检查点恢复任务',
    'run.retry_requested': '任务已重新入队',
    'planner.started': '正在生成执行计划',
    'planner.completed': '执行计划生成完成',
    'planner.degraded': '模型规划不可用，已进入受限模式',
    'planner.blocked': '执行计划无法继续',
    'tool.started': '正在执行工具',
    'tool.completed': '工具执行完成',
    'tool.failed': '工具执行失败',
    'verification.verified': '业务结果已核验',
    'verification.inconclusive': '执行结束，业务结果待核验',
    'verification.failed': '业务结果验收失败',
    'run.verification_inconclusive': '任务已执行，仍缺少独立业务回执',
    'ledger.updated': '任务账本已更新',
    'step.waiting_user': '等待用户确认',
    'step.blocked': '步骤依赖未满足',
    'step.retry_scheduled': '步骤已安排重试',
    'step.repair_applied': '步骤已修复并继续执行',
    'step.recovered': '步骤已从检查点恢复',
    'step.recovery_confirmation_required': '中断步骤需要确认后继续',
    'run.completed': '智能任务执行完成',
    'run.failed': '智能任务执行失败',
  }
  return labels[type] || '执行状态已更新'
}

function statusFromEvents(events: AgentRunEvent[]): TaskItem['status'] {
  const decisive = [...events].reverse().find((event) => [
    'run.completed',
    'run.failed',
    'run.cancelled',
    'run.paused',
    'run.resumed',
    'run.recovered',
    'run.retry_requested',
    'run.queued',
    'run.background_started',
    'step.retry_scheduled',
    'step.repair_applied',
    'planner.blocked',
    'step.blocked',
    'step.waiting_user',
    'tool.started',
    'tool.completed',
    'tool.failed',
  ].includes(event.event_type))
  if (decisive?.event_type === 'run.completed') return 'success'
  if (decisive?.event_type === 'run.cancelled') return 'cancelled'
  if (decisive?.event_type === 'run.paused') return 'paused'
  if (['run.failed', 'planner.blocked', 'step.blocked', 'tool.failed'].includes(decisive?.event_type || '')) {
    return 'failed'
  }
  if (decisive?.event_type === 'step.waiting_user') return 'queued'
  return events.length ? 'running' : 'queued'
}

function statusFromRun(status: string): TaskItem['status'] | null {
  const normalized = asString(status).trim()
  if (normalized === 'completed') return 'success'
  if (normalized === 'failed') return 'failed'
  if (normalized === 'cancelled') return 'cancelled'
  if (normalized === 'paused') return 'paused'
  if (normalized === 'waiting_user' || normalized === 'queued') return 'queued'
  if (ACTIVE_RUN_STATUSES.has(normalized)) return 'running'
  return null
}

function progressFromEvents(events: AgentRunEvent[], status: TaskItem['status']): number {
  if (status === 'success' || status === 'failed' || status === 'cancelled') return 100
  if (status === 'paused') return 60
  if (!events.length) return 5
  const lastPauseControl = [...events].reverse().find((event) =>
    ['run.paused', 'run.resumed'].includes(event.event_type),
  )
  if (lastPauseControl?.event_type === 'run.paused') return 60
  if (events.some((event) => event.event_type === 'step.waiting_user')) return 85
  if (events.some((event) => event.event_type === 'tool.completed')) return 80
  if (events.some((event) => event.event_type === 'tool.started')) return 55
  if (events.some((event) => event.event_type === 'planner.completed')) return 35
  if (events.some((event) => event.event_type === 'planner.started')) return 15
  return 10
}

const EVIDENCE_KINDS = new Set<OrchestrationEvidenceKind>([
  'employee',
  'print',
  'database_write',
  'database_read',
  'tool',
])

function normalizeOrchestrationEvidence(rawValue: unknown): OrchestrationEvidence | null {
  const raw = asRecord(rawValue)
  const rawKind = asString(raw.kind).trim() as OrchestrationEvidenceKind
  if (!EVIDENCE_KINDS.has(rawKind)) return null

  const databases = asArray<Record<string, unknown>>(raw.databases).map((database) => ({
    database_id: asString(database.database_id),
    database_name: asString(database.database_name),
    runtime_database: asString(database.runtime_database),
    storage_mode: asString(database.storage_mode),
    role: asString(database.role),
    tables: asString(database.tables),
    active_mod_id: asString(database.active_mod_id),
  })) as OrchestrationDatabase[]
  const changes = asArray<Record<string, unknown>>(raw.changes).map((change) => {
    const counts = asRecord(change.counts)
    return {
      database_id: asString(change.database_id),
      database_name: asString(change.database_name),
      runtime_database: asString(change.runtime_database),
      entity: asString(change.entity),
      operation: asString(change.operation),
      label: asString(change.label),
      counts: {
        created: asNumber(counts.created, 0),
        updated: asNumber(counts.updated, 0),
        deleted: asNumber(counts.deleted, 0),
      },
      items: asArray<Record<string, unknown>>(change.items).slice(0, 12),
      field_changes: asArray<Record<string, unknown>>(change.field_changes)
        .slice(0, 20)
        .map((field) => ({
          field: asString(field.field),
          before: asString(field.before),
          after: asString(field.after),
        })),
    }
  }) as OrchestrationChange[]
  const employees = asArray<Record<string, unknown>>(raw.employees).map((employee) => ({
    employee_id: asString(employee.employee_id),
    employee_name: asString(employee.employee_name),
    task: asString(employee.task),
    status: asString(employee.status),
  })) as OrchestrationEmployee[]
  const printRaw = asRecord(raw.print)
  const print = raw.print && Object.keys(printRaw).length
    ? {
        kind: asString(printRaw.kind),
        printer_name: asString(printRaw.printer_name),
        copies: asNumber(printRaw.copies, 1),
        template: asString(printRaw.template),
        file_name: asString(printRaw.file_name),
        job_id: asString(printRaw.job_id),
      } as OrchestrationPrint
    : undefined

  return {
    schema_version: asString(raw.schema_version),
    kind: rawKind,
    label: asString(raw.label),
    status: asString(raw.status),
    tool_id: asString(raw.tool_id),
    action: asString(raw.action),
    databases,
    changes,
    employees,
    ...(print ? { print } : {}),
    ...(asString(raw.query) ? { query: asString(raw.query) } : {}),
    ...(raw.result_count !== undefined ? { result_count: asNumber(raw.result_count, 0) } : {}),
  }
}

function eventStatus(event: AgentRunEvent, evidence: OrchestrationEvidence): string {
  const explicit = asString(evidence.status).trim()
  if (explicit) return explicit
  if (event.event_type === 'tool.started') return 'running'
  if (event.event_type === 'tool.failed') return 'failed'
  if (event.event_type === 'tool.completed') return 'completed'
  return 'observed'
}

function normalizeVerification(rawValue: unknown): OrchestrationVerification | undefined {
  const raw = asRecord(rawValue)
  if (!Object.keys(raw).length) return undefined
  return {
    accepted: raw.accepted === true,
    verified: raw.verified === true,
    status: asString(raw.status),
    verifier: asString(raw.verifier),
    reason: asString(raw.reason),
    evidence: asRecord(raw.evidence),
    recovery_hint: asString(raw.recovery_hint),
  }
}

/** Collapse started/completed events for the same call into one readable row. */
export function buildOrchestrationTrace(events: AgentRunEvent[]): OrchestrationTraceStep[] {
  const traceByCallId = new Map<string, OrchestrationTraceStep>()
  for (const event of events) {
    const data = asRecord(event.data)
    const evidence = normalizeOrchestrationEvidence(data.orchestration)
    if (!evidence) continue
    const callId = asString(data.call_id).trim()
      || asString(data.step_id).trim()
      || `event_${asString(event.event_id)}`
    const existing = traceByCallId.get(callId)
    const verification = normalizeVerification(data.verification)
    const next: OrchestrationTraceStep = {
      id: callId,
      eventId: asString(event.event_id),
      firstEventId: existing?.firstEventId || asString(event.event_id),
      eventType: event.event_type,
      createdAt: event.created_at,
      stepId: asString(data.step_id),
      nodeId: asString(data.node_id),
      status: verification?.status || eventStatus(event, evidence),
      message: asString(event.message),
      evidence,
      ...(verification ? { verification } : {}),
    }
    traceByCallId.set(callId, existing ? { ...existing, ...next } : next)
  }
  return Array.from(traceByCallId.values())
}

export function buildAgentRunTaskUpdate(params: {
  runId: string
  userText?: string
  events?: AgentRunEvent[]
  messageRef?: string
  runStatus?: string
}): Partial<TaskItem> & { id: string; title: string; source: TaskItem['source']; type: string } {
  const events = asArray<AgentRunEvent>(params.events)
  const last = events[events.length - 1]
  const eventStatus = statusFromEvents(events)
  const status = statusFromRun(asString(params.runStatus)) || eventStatus
  const stage = last ? eventLabel(last) : '等待执行状态'
  const errorEvent = [...events].reverse().find((event) =>
    ['run.failed', 'tool.failed', 'verification.failed', 'planner.blocked', 'step.blocked'].includes(event.event_type),
  )
  const needsVerification = events.some((event) =>
    ['verification.inconclusive', 'run.verification_inconclusive'].includes(event.event_type),
  )
  const orchestrationTrace = buildOrchestrationTrace(events)
  const userTitle = asString(params.userText).trim().slice(0, 30)
  return {
    id: `agent_${params.runId}`,
    type: 'agent_run',
    source: 'agent',
    title: `智能任务：${userTitle || params.runId}`,
    status,
    progress: progressFromEvents(events, status),
    stage,
    summary: status === 'success'
      ? (needsVerification ? '任务已执行，结果待核验' : '智能任务执行完成')
      : status === 'paused'
        ? '任务已保存检查点，可随时继续'
        : status === 'cancelled'
          ? '任务已取消，已完成步骤仍保留'
      : stage,
    error: status === 'failed' && errorEvent ? eventLabel(errorEvent) : '',
    messageRef: params.messageRef,
    payload: {
      agentRunId: params.runId,
      agentEvents: events,
      orchestrationTrace,
      lastAgentEventId: asString(last?.event_id),
      needsVerification,
      terminal: ['success', 'failed', 'cancelled'].includes(status)
        || (last ? TERMINAL_EVENT_TYPES.has(last.event_type) : false),
      runStatus: params.runStatus || '',
    },
  }
}

export function useAgentRunEventSync(options: UseAgentRunEventSyncOptions) {
  const lastEventByRunId = new Map<string, string>()
  const eventsByRunId = new Map<string, AgentRunEvent[]>()
  const userTextByRunId = new Map<string, string>()
  const pollingTimers = new Map<string, number>()

  function reconcileWorkflowTask(run: AgentRun): void {
    const planId = asString(run.plan_id).trim()
    const runStatus = statusFromRun(asString(run.status))
    if (!runStatus || !['success', 'failed', 'cancelled'].includes(runStatus)) return
    const messageToken = asString(run.message).trim().slice(0, 30)
    const workflowTask = (options.getTasks?.() || []).find(
      (task) => task.type === 'workflow'
        && ['queued', 'running'].includes(task.status)
        && (
          (!!planId && task.id === planId)
          || (!!messageToken && task.title.includes(messageToken))
        ),
    )
    if (!workflowTask) return
    options.upsertTask({
      id: workflowTask.id,
      type: workflowTask.type,
      source: workflowTask.source,
      title: workflowTask.title,
      status: runStatus,
      progress: 100,
      stage: runStatus === 'success'
        ? '执行完成'
        : runStatus === 'cancelled'
          ? '任务已取消'
          : '执行失败',
      summary: runStatus === 'success'
        ? '工作流执行完成'
        : runStatus === 'cancelled'
          ? '工作流已取消'
          : '工作流执行失败',
      error: runStatus === 'failed' ? (asString(run.error).trim() || '工作流执行失败') : '',
      payload: {
        ...(workflowTask.payload || {}),
        agentRunId: run.run_id,
        runStatus: run.status,
        terminal: true,
      },
    })
  }

  function mergeRunEvents(runId: string, events: AgentRunEvent[]): AgentRunEvent[] {
    const previousEvents = eventsByRunId.get(runId) || []
    const mergedEvents = new Map<string, AgentRunEvent>()
    for (const event of [...previousEvents, ...events]) {
      const eventId = asString(event.event_id).trim()
      if (eventId) mergedEvents.set(eventId, event)
    }
    const allEvents = Array.from(mergedEvents.values())
    eventsByRunId.set(runId, allEvents)
    const last = allEvents[allEvents.length - 1]
    if (last?.event_id) lastEventByRunId.set(runId, last.event_id)
    return allEvents
  }

  function applyRunSnapshot(run: AgentRun, userText = ''): void {
    const runId = asString(run.run_id).trim()
    if (!runId) return
    const resolvedText = userText || asString(run.message)
    userTextByRunId.set(runId, resolvedText)
    const allEvents = mergeRunEvents(runId, asArray<AgentRunEvent>(run.events))
    const update = buildAgentRunTaskUpdate({
      runId,
      userText: resolvedText,
      events: allEvents,
      messageRef: options.getLastAiMessageRef?.() || '',
      runStatus: asString(run.status),
    })
    options.upsertTask(update)
    reconcileWorkflowTask(run)
    options.attachOrchestrationTrace?.(
      asArray<OrchestrationTraceStep>(update.payload?.orchestrationTrace),
    )
    if (ACTIVE_RUN_STATUSES.has(asString(run.status))) {
      watchAgentRun(runId, resolvedText)
    } else {
      stopWatching(runId)
    }
  }

  async function syncAgentRunEvents(runId: string, userText = ''): Promise<TaskItem['status'] | null> {
    const normalizedRunId = String(runId || '').trim()
    if (!normalizedRunId) return null
    if (userText) userTextByRunId.set(normalizedRunId, userText)
    const afterEventId = lastEventByRunId.get(normalizedRunId)
    try {
      const response = await agentRunsApi.listEvents(
        normalizedRunId,
        afterEventId ? { after_event_id: afterEventId } : {},
      )
      const events = Array.isArray(response?.data) ? response.data : []
      const allEvents = mergeRunEvents(normalizedRunId, events)
      const update = buildAgentRunTaskUpdate({
        runId: normalizedRunId,
        userText: userTextByRunId.get(normalizedRunId) || userText,
        events: allEvents,
        messageRef: options.getLastAiMessageRef?.() || '',
      })
      options.upsertTask(update)
      options.attachOrchestrationTrace?.(
        asArray<OrchestrationTraceStep>(update.payload?.orchestrationTrace),
      )
      return update.status || null
    } catch {
      const update = buildAgentRunTaskUpdate({
        runId: normalizedRunId,
        userText: userTextByRunId.get(normalizedRunId) || userText,
        events: eventsByRunId.get(normalizedRunId) || [],
        messageRef: options.getLastAiMessageRef?.() || '',
      })
      options.upsertTask(update)
      return update.status || null
    }
  }

  function stopWatching(runId: string): void {
    const timer = pollingTimers.get(runId)
    if (timer !== undefined) window.clearTimeout(timer)
    pollingTimers.delete(runId)
  }

  function watchAgentRun(runId: string, userText = ''): void {
    const normalizedRunId = asString(runId).trim()
    if (!normalizedRunId || pollingTimers.has(normalizedRunId)) return
    if (userText) userTextByRunId.set(normalizedRunId, userText)
    const poll = async () => {
      pollingTimers.delete(normalizedRunId)
      const status = await syncAgentRunEvents(
        normalizedRunId,
        userTextByRunId.get(normalizedRunId) || '',
      )
      if (status === 'running' || status === 'queued') {
        pollingTimers.set(normalizedRunId, window.setTimeout(poll, 1400))
      }
    }
    pollingTimers.set(normalizedRunId, window.setTimeout(poll, 500))
  }

  async function syncAgentRunFromPayload(payload: unknown, userText = ''): Promise<void> {
    const runId = extractAgentRunId(payload)
    if (!runId) return
    const status = await syncAgentRunEvents(runId, userText)
    if (status === 'running' || status === 'queued') watchAgentRun(runId, userText)
  }

  async function restoreAgentRuns(userId = ''): Promise<void> {
    try {
      const response = await agentRunsApi.listRuns({
        ...(userId ? { user_id: userId } : {}),
        limit: 50,
      })
      const runs = asArray<AgentRun>(response?.data)
      const trackedTasks = options.getTasks?.() || []
      const trackedTaskIds = new Set(trackedTasks.map((task) => task.id))
      for (const run of runs) {
        const runId = asString(run.run_id).trim()
        const messageToken = asString(run.message).trim().slice(0, 30)
        const isTracked = trackedTaskIds.has(`agent_${runId}`)
          || (!!run.plan_id && trackedTaskIds.has(asString(run.plan_id)))
          || trackedTasks.some(
            (task) => task.type === 'workflow'
              && ['queued', 'running'].includes(task.status)
              && !!messageToken
              && task.title.includes(messageToken),
          )
        if (
          isTracked
          ||
          ACTIVE_RUN_STATUSES.has(asString(run.status))
          || ['paused', 'waiting_user'].includes(asString(run.status))
        ) {
          applyRunSnapshot(run, asString(run.message))
        }
      }
    } catch {
      // The task panel can still recover from its session snapshot.
    }
  }

  async function controlAgentRun(
    runId: string,
    action: 'pause' | 'resume' | 'cancel' | 'retry',
    requestedBy = '',
  ): Promise<void> {
    const method = {
      pause: agentRunsApi.pauseRun,
      resume: agentRunsApi.resumeRun,
      cancel: agentRunsApi.cancelRun,
      retry: agentRunsApi.retryRun,
    }[action]
    const response = await method(runId, { requested_by: requestedBy })
    if (response?.data) applyRunSnapshot(response.data, userTextByRunId.get(runId) || '')
  }

  function dispose(): void {
    for (const runId of pollingTimers.keys()) stopWatching(runId)
  }

  return {
    syncAgentRunEvents,
    syncAgentRunFromPayload,
    restoreAgentRuns,
    controlAgentRun,
    dispose,
  }
}

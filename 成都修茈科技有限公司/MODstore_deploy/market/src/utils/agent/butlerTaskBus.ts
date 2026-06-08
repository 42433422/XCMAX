export type ButlerTaskPublishPayload = {
  source: string
  employeeId: string
  employeeName?: string
  brief: string
  inputData?: Record<string, unknown>
  includeDependencies?: boolean
  allowHighRisk?: boolean
  maxConcurrency?: number
}

export type ButlerTaskPublishEvent = ButlerTaskPublishPayload & {
  version: 1
  eventId: string
  emittedAt: number
}

const TASK_EVENT = 'xc:butler:publish-task'
const CHANNEL_NAME = 'xc-butler-task-broadcast-v1'
const localBus = new EventTarget()
const seenEventIds = new Set<string>()
const originId = `origin-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
let channel: BroadcastChannel | null | undefined

function ensureChannel(): BroadcastChannel | null {
  if (channel !== undefined) return channel
  if (typeof window === 'undefined' || typeof BroadcastChannel === 'undefined') {
    channel = null
    return channel
  }
  channel = new BroadcastChannel(CHANNEL_NAME)
  return channel
}

function rememberEventId(eventId: string): void {
  seenEventIds.add(eventId)
  if (seenEventIds.size <= 120) return
  const oldest = seenEventIds.values().next()
  if (!oldest.done) seenEventIds.delete(oldest.value)
}

function toEvent(payload: ButlerTaskPublishPayload): ButlerTaskPublishEvent {
  return {
    version: 1,
    eventId: `evt-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    emittedAt: Date.now(),
    source: String(payload.source || 'unknown'),
    employeeId: String(payload.employeeId || '').trim(),
    employeeName: payload.employeeName ? String(payload.employeeName) : undefined,
    brief: String(payload.brief || '').trim(),
    inputData: payload.inputData && typeof payload.inputData === 'object' ? payload.inputData : {},
    includeDependencies: payload.includeDependencies !== false,
    allowHighRisk: Boolean(payload.allowHighRisk),
    maxConcurrency: Number(payload.maxConcurrency || 2) || 2,
  }
}

function isTaskEvent(value: unknown): value is ButlerTaskPublishEvent {
  if (!value || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  return (
    row.version === 1 &&
    typeof row.eventId === 'string' &&
    typeof row.emittedAt === 'number' &&
    typeof row.source === 'string' &&
    typeof row.employeeId === 'string' &&
    typeof row.brief === 'string'
  )
}

function dispatchLocal(event: ButlerTaskPublishEvent): void {
  if (!event.employeeId || !event.brief) return
  if (seenEventIds.has(event.eventId)) return
  rememberEventId(event.eventId)
  localBus.dispatchEvent(new CustomEvent<ButlerTaskPublishEvent>(TASK_EVENT, { detail: event }))
}

export function publishButlerTask(payload: ButlerTaskPublishPayload): ButlerTaskPublishEvent {
  const event = toEvent(payload)
  dispatchLocal(event)
  const bc = ensureChannel()
  try {
    bc?.postMessage({
      topic: TASK_EVENT,
      originId,
      event,
    })
  } catch {
    // ignore broadcast failures; local delivery already happened.
  }
  return event
}

export function subscribeButlerTask(handler: (event: ButlerTaskPublishEvent) => void): () => void {
  const onLocal = (ev: Event) => {
    const detail = (ev as CustomEvent<ButlerTaskPublishEvent | undefined>).detail
    if (!detail || !isTaskEvent(detail)) return
    handler(detail)
  }
  localBus.addEventListener(TASK_EVENT, onLocal as EventListener)

  const bc = ensureChannel()
  const onMessage = (ev: MessageEvent) => {
    const data = ev.data as
      | {
          topic?: unknown
          originId?: unknown
          event?: unknown
        }
      | undefined
    if (!data || data.topic !== TASK_EVENT) return
    if (typeof data.originId === 'string' && data.originId === originId) return
    if (!isTaskEvent(data.event)) return
    dispatchLocal(data.event)
  }
  bc?.addEventListener('message', onMessage)

  return () => {
    localBus.removeEventListener(TASK_EVENT, onLocal as EventListener)
    bc?.removeEventListener('message', onMessage)
  }
}

export function buildButlerTaskPrompt(event: ButlerTaskPublishEvent): string {
  const target = event.employeeName
    ? `${event.employeeName} (${event.employeeId})`
    : event.employeeId
  const inputDataJson = JSON.stringify(event.inputData || {}, null, 2)
  return [
    '请处理一条来自「在岗员工节点图」的任务发布请求。',
    `目标员工：${target}`,
    `任务 brief：${event.brief}`,
    `include_dependencies=${event.includeDependencies ? 'true' : 'false'}，max_concurrency=${event.maxConcurrency || 2}`,
    `allow_high_risk_real_run=${event.allowHighRisk ? 'true' : 'false'}`,
    `input_data: ${inputDataJson}`,
    '请先复述任务并给出执行计划，然后开始执行。',
  ].join('\n')
}

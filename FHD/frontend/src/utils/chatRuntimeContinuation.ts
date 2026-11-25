import type { ChatRuntimeContinuation, UiChatMessage } from '@/types/chat-ui'
import type { ChatPlannerPayload } from '@/types/chat'
import { asRecord, asString } from '@/utils/typeGuards'

const WAITING = new Set(['waiting_user', 'waiting_approval'])
/** Queued work keeps its run id for event following, but never blocks a new turn. */
const FOLLOWING = new Set(['queued'])

function keepsRunId(status: string): boolean {
  return WAITING.has(status) || FOLLOWING.has(status)
}

export function restoreRuntimeContinuation(raw: unknown): ChatRuntimeContinuation | undefined {
  const value = asRecord(raw)
  const status = asString(value.status).trim()
  const sessionId = asString(value.sessionId).trim()
  if (!status || status.length > 64 || !sessionId || sessionId.length > 512) return undefined
  const runId = value.runId
  if (runId !== null && (typeof runId !== 'string' || !/^[\w.:-]{1,256}$/.test(runId))) return undefined
  return { runId: keepsRunId(status) ? runId as string | null : null, status, sessionId }
}

export function runtimeContinuationFromPayload(payload: ChatPlannerPayload): ChatRuntimeContinuation | undefined {
  const envelope = asRecord(payload.data)
  if (payload.runtime !== 'xiaox' && envelope.runtime !== 'xiaox') return undefined
  const update = asRecord(payload.runtime_context_update)
  return restoreRuntimeContinuation({
    runId: update.agent_runtime_run_id,
    status: update.status || runtimeExecutionState(payload),
    sessionId: update.conversation_id,
  })
}

export function runtimeExecutionState(payload: ChatPlannerPayload): string {
  return asString(payload.execution_state || asRecord(payload.data).execution_state).trim()
}

export function isRuntimeWaiting(payload: ChatPlannerPayload): boolean {
  const envelope = asRecord(payload.data)
  return (payload.runtime === 'xiaox' || envelope.runtime === 'xiaox')
    && WAITING.has(runtimeExecutionState(payload))
}

/** The durable queue accepted the turn; follow the run instead of finalizing. */
export function isRuntimeQueued(payload: ChatPlannerPayload): boolean {
  const envelope = asRecord(payload.data)
  return (payload.runtime === 'xiaox' || envelope.runtime === 'xiaox')
    && runtimeExecutionState(payload) === 'queued'
}

/** Only the latest actual assistant reply can ask to continue its parent. */
export function pendingRuntimeRunId(messages: UiChatMessage[], sessionId: string): string | undefined {
  const latest = [...messages].reverse().find(message => message.role === 'ai' && !message.streamingShell)
  const continuation = restoreRuntimeContinuation(latest?.runtimeContinuation)
  if (!continuation || continuation.sessionId !== sessionId || !WAITING.has(continuation.status)) return undefined
  return continuation.runId || undefined
}

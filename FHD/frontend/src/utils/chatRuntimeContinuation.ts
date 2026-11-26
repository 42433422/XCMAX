import type { ChatRuntimeContinuation, UiChatMessage } from '@/types/chat-ui'
import type { ChatPlannerPayload } from '@/types/chat'
import { asRecord, asString } from '@/utils/typeGuards'

const WAITING = new Set(['waiting_user', 'waiting_approval'])
const RUNTIMES = new Set(['codex', 'xiaox'])
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

/** Historical wire labels identify the same runtime, not another executor. */
export function isFixedRuntimePayload(payload: ChatPlannerPayload): boolean {
  const outer = asString(payload.runtime).trim()
  const inner = asString(asRecord(payload.data).runtime).trim()
  return Boolean(outer || inner) && (!outer || RUNTIMES.has(outer)) && (!inner || RUNTIMES.has(inner))
}

export function runtimeContinuationFromPayload(payload: ChatPlannerPayload): ChatRuntimeContinuation | undefined {
  if (!isFixedRuntimePayload(payload)) return undefined
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
  return isFixedRuntimePayload(payload)
    && WAITING.has(runtimeExecutionState(payload))
}

/** The durable queue accepted the turn; follow the run instead of finalizing. */
export function isRuntimeQueued(payload: ChatPlannerPayload): boolean {
  return isFixedRuntimePayload(payload)
    && runtimeExecutionState(payload) === 'queued'
}

/** Only the latest actual assistant reply can ask to continue its parent. */
export function pendingRuntimeRunId(messages: UiChatMessage[], sessionId: string): string | undefined {
  const latest = [...messages].reverse().find(message => message.role === 'ai' && !message.streamingShell)
  const continuation = restoreRuntimeContinuation(latest?.runtimeContinuation)
  if (!continuation || continuation.sessionId !== sessionId || !WAITING.has(continuation.status)) return undefined
  return continuation.runId || undefined
}

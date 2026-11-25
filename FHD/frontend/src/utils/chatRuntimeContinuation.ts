import type { ChatRuntimeContinuation, UiChatMessage } from '@/types/chat-ui'
import type { ChatPlannerPayload } from '@/types/chat'
import { asRecord, asString } from '@/utils/typeGuards'

const WAITING = new Set(['waiting_user', 'waiting_approval'])
const RUNTIMES = new Set(['codex', 'xiaox'])

function isRuntimePayload(payload: ChatPlannerPayload): boolean {
  const outer = asString(payload.runtime).trim()
  const inner = asString(asRecord(payload.data).runtime).trim()
  // Both labels refer to the same runtime contract during migration. A
  // conflicting non-runtime label must not authorize a continuation hint.
  return Boolean(outer || inner) && (!outer || RUNTIMES.has(outer)) && (!inner || RUNTIMES.has(inner))
}

export function restoreRuntimeContinuation(raw: unknown): ChatRuntimeContinuation | undefined {
  const value = asRecord(raw)
  const status = asString(value.status).trim()
  const sessionId = asString(value.sessionId).trim()
  if (!status || status.length > 64 || !sessionId || sessionId.length > 512) return undefined
  const runId = value.runId
  if (runId !== null && (typeof runId !== 'string' || !/^[\w.:-]{1,256}$/.test(runId))) return undefined
  return { runId: WAITING.has(status) ? runId as string | null : null, status, sessionId }
}

export function runtimeContinuationFromPayload(payload: ChatPlannerPayload): ChatRuntimeContinuation | undefined {
  if (!isRuntimePayload(payload)) return undefined
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
  return isRuntimePayload(payload) && WAITING.has(runtimeExecutionState(payload))
}

/** Only the latest actual assistant reply can ask to continue its parent. */
export function pendingRuntimeRunId(messages: UiChatMessage[], sessionId: string): string | undefined {
  const latest = [...messages].reverse().find(message => message.role === 'ai' && !message.streamingShell)
  const continuation = restoreRuntimeContinuation(latest?.runtimeContinuation)
  if (!continuation || continuation.sessionId !== sessionId || !WAITING.has(continuation.status)) return undefined
  return continuation.runId || undefined
}

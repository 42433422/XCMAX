import type { ChatStatus } from 'ai'
import { computed, reactive, type Ref } from 'vue'
import agentRunsApi from '@/api/agentRuns'
import type { ChatPlannerPayload } from '@/types/chat'
import type { UiChatMessageExtras } from '@/types/chat-ui'
import { parseApprovalCardFromPayload } from '@/utils/chatApprovalCard'
import { isRuntimeWaiting, runtimeContinuationFromPayload } from '@/utils/chatRuntimeContinuation'
import { plannerExecutionState } from './chat-orchestration/chatOrchestrationShared'

export type ChatConversationStatus = ChatStatus | 'waiting' | 'review' | 'stopped'

export const isChatConversationBusy = (status?: ChatConversationStatus) => status === 'submitted' || status === 'streaming'
const normalizeId = (id: string) => String(id || '').trim() || 'default'

export function useChatSessionActivity(activeSessionId: Ref<string>, getIdentity = () => '') {
  const activity = reactive(new Map<string, { sessionId: string; identity: string; status: ChatConversationStatus }>())
  const keyOf = (sessionId: string) => JSON.stringify([getIdentity(), normalizeId(sessionId)])
  const statuses = computed(() => Object.fromEntries([...activity.values()]
    .filter(entry => entry.identity === getIdentity())
    .map(entry => [entry.sessionId, entry.status])))
  const isSessionBusy = (sessionId: string) => isChatConversationBusy(activity.get(keyOf(sessionId))?.status)
  const isLoading = computed(() => isSessionBusy(activeSessionId.value))
  const isStreamingReply = computed(() => activity.get(keyOf(activeSessionId.value))?.status === 'streaming')

  const generations = new Map<string, AbortController>()
  function cancelSession(sessionId = activeSessionId.value): boolean {
    const key = keyOf(sessionId)
    const wasBusy = isSessionBusy(sessionId)
    generations.get(key)?.abort()
    generations.delete(key)
    if (wasBusy) forSession(sessionId).setStatus('stopped')
    return wasBusy
  }
  function cancelAll() {
    generations.forEach(controller => controller.abort())
    generations.clear()
    activity.clear()
  }
  function beginRound(sessionId = activeSessionId.value) {
    const key = keyOf(sessionId)
    cancelSession(sessionId)
    const controller = new AbortController()
    generations.set(key, controller)
    const isCurrent = () => generations.get(key) === controller && !controller.signal.aborted
    const room = forSession(sessionId)
    return {
      signal: controller.signal,
      isCurrent,
      setLoading: (value: boolean) => { if (isCurrent()) room.setLoading(value) },
    }
  }

  function captureGeneration(sessionId = activeSessionId.value) {
    const key = keyOf(sessionId)
    const generation = generations.get(key)
    return () => generations.get(key) === generation && !generation?.signal.aborted
  }

  function forSession(sessionId = activeSessionId.value) {
    const id = normalizeId(sessionId)
    const identity = getIdentity()
    const key = keyOf(id)
    const setStatus = (status: ChatConversationStatus) => activity.set(key, { sessionId: id, identity, status })
    return {
      sessionId: id,
      isActive: () => normalizeId(activeSessionId.value) === id && getIdentity() === identity,
      setStatus,
      setLoading(active: boolean) {
        const status = activity.get(key)?.status
        if (active && !isChatConversationBusy(status)) setStatus('submitted')
        if (!active && isChatConversationBusy(status)) setStatus('ready')
      },
      setStreaming(active: boolean) {
        if (active) setStatus('streaming')
        else if (activity.get(key)?.status === 'streaming') setStatus('submitted')
      },
    }
  }

  return { isLoading, isStreamingReply, isSessionBusy, statuses, forSession, captureGeneration, beginRound, cancelSession, cancelAll }
}

export async function persistDetachedPlannerResult(
  data: ChatPlannerPayload,
  sessionId: string,
  save: (role: 'ai', content: string, sessionId: string, extras?: UiChatMessageExtras) => Promise<void>,
): Promise<void> {
  const parts = data.batch && Array.isArray(data.results) ? data.results.map((item) => item as ChatPlannerPayload) : [data]
  for (const part of parts) {
    const text = part.success || isRuntimeWaiting(part) ? String(part.response || part.message || '') : `处理失败: ${part.message || '未知错误'}`
    const continuation = runtimeContinuationFromPayload(part)
    const approvalCard = continuation ? parseApprovalCardFromPayload(part) : null
    const extras: UiChatMessageExtras = {
      ...(continuation?.sessionId === sessionId ? { runtimeContinuation: continuation, workflowAction: plannerExecutionState(part) } : {}),
      ...(approvalCard ? { approvalCard } : {}),
    }
    if (Object.keys(extras).length) await save('ai', text, sessionId, extras)
    else await save('ai', text, sessionId)
  }
}

export async function recordProductFastPathTask(
  sessionId: string,
  message: string,
  keyword: string,
  rows: Record<string, unknown>[],
  total: number,
  response: string,
): Promise<void> {
  await agentRunsApi.observeTool({
    message,
    tool_id: 'products',
    action: 'query',
    params: { keyword, page: 1, per_page: 20 },
    output: { success: true, returned: rows.length, total },
    response,
    source: 'desktop_product_fast_path',
    runtime_context: {
      task_id: sessionId,
      conversation_id: sessionId,
      session_id: sessionId,
      task_title: message.slice(0, 80),
      route: 'products.searchProducts',
    },
  })
}

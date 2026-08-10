import { computed, ref, type Ref } from 'vue'
import agentRunsApi from '@/api/agentRuns'
import type { ChatPlannerPayload } from '@/types/chat'

function updateIds(ids: Ref<Set<string>>, sessionId: string, active: boolean): void {
  const next = new Set(ids.value)
  if (active) next.add(sessionId)
  else next.delete(sessionId)
  ids.value = next
}

export function useChatSessionActivity(activeSessionId: Ref<string>) {
  const runningIds = ref<Set<string>>(new Set())
  const streamingIds = ref<Set<string>>(new Set())
  const isLoading = computed(() => runningIds.value.has(activeSessionId.value))
  const isStreamingReply = computed(() => streamingIds.value.has(activeSessionId.value))

  function forSession(sessionId = activeSessionId.value) {
    const id = String(sessionId || '').trim() || 'default'
    return {
      sessionId: id,
      isActive: () => activeSessionId.value === id,
      setLoading: (active: boolean) => updateIds(runningIds, id, active),
      setStreaming: (active: boolean) => updateIds(streamingIds, id, active),
    }
  }

  return { isLoading, isStreamingReply, forSession, runningIds, streamingIds }
}

export async function persistDetachedPlannerResult(
  data: ChatPlannerPayload,
  sessionId: string,
  save: (role: 'ai', content: string, sessionId: string) => Promise<void>,
): Promise<void> {
  const parts = data.batch && Array.isArray(data.results) ? data.results.map((item) => item as ChatPlannerPayload) : [data]
  for (const part of parts) {
    await save('ai', part.success ? String(part.response || '') : `处理失败: ${part.message || '未知错误'}`, sessionId)
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
    output: { success: true, data: rows, total },
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

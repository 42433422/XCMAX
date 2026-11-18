import { resolvePlannerChatStreamPath } from '@/utils/plannerChatPaths'
import { createParser } from 'eventsource-parser'
import type { ChatTraceItem } from '@/composables/chat-orchestration/chatOrchestrationShared'

export type PlannerSseEvent =
  | { type: 'route_metadata'; route_metadata: unknown }
  /** 正文之前的工具执行轨迹（附件工件取数），由气泡「附件读取」展示 */
  | { type: 'trace'; items?: ChatTraceItem[]; turn_id?: string }
  | { type: 'model_activity' }
  /** 即时思考说明：执行线程在规划/审批/执行节点推来的过程文本 */
  | { type: 'thinking'; id?: string; delta: string }
  | { type: 'token'; text: string; ephemeral?: boolean }
  | { type: 'tool_progress'; label?: string; text?: string; phase?: string; run_id?: string }
  | {
      type: 'tool_call'
      phase?: 'started' | 'progress' | 'finished'
      node_id?: string
      tool_id?: string
      action?: string
      params?: Record<string, unknown>
      success?: boolean
      duration_ms?: number
      output_preview?: string
      error?: string
      retries?: number
      recovery_hint?: string
      label?: string
      progress?: number
      processed_rows?: number
      total_rows?: number
    }
  | { type: 'done'; result?: unknown }
  | { type: 'error'; result?: unknown; message?: string; status_code?: number; run_id?: string; route_metadata?: unknown; execution_outcome?: string; requires_reconciliation?: boolean }
  | { type: 'requires_token'; token_name?: string; token_description?: string; run_id?: string }

export class IncompletePlannerSseError extends Error {
  constructor() {
    super('连接提前结束，尚未收到完成回执。请核对原任务状态，勿重复提交可能已执行的操作。')
    this.name = 'IncompletePlannerSseError'
  }
}

/** 读取 ``fetch`` 得到的 SSE（``text/event-stream``）响应体并逐条回调事件 */
export async function readPlannerSseResponse(response: Response, onEvent: (ev: PlannerSseEvent) => void, signal?: AbortSignal): Promise<void> {
  if (!response.body) {
    throw new Error('响应体不可读（可能被代理缓冲或未返回流）')
  }
  const reader = response.body.getReader()
  const abort = () => { void reader.cancel().catch(() => undefined) }
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) abort()
  const decoder = new TextDecoder()
  let terminalError = false
  let completed = false
  const parser = createParser({
    onEvent: ({ data }) => {
      if (terminalError || !data.trim()) return
      let ev: PlannerSseEvent
      try { ev = JSON.parse(data) as PlannerSseEvent } catch { return }
      if (!ev || typeof ev.type !== 'string') return
      terminalError = ev.type === 'error'
      // The backend may end with an explicit authorization pause. Progress
      // after either receipt still requires a new terminal event before EOF.
      completed = ev.type === 'done' || ev.type === 'requires_token'
      onEvent(ev)
    },
  })
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (signal?.aborted) throw new DOMException('请求已中断', 'AbortError')
      if (done) break
      parser.feed(decoder.decode(value, { stream: true }))
      if (terminalError) return
    }
    // Retain the legacy endpoint's final event without a trailing separator.
    parser.feed(decoder.decode() + '\n\n')
    if (terminalError) return
    if (!completed) throw new IncompletePlannerSseError()
  } finally {
    signal?.removeEventListener('abort', abort)
    if (terminalError) void reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}

export function resolveChatStreamPath(): string {
  return resolvePlannerChatStreamPath()
}

const WORKFLOW_CONTROL_WORDS = new Set([
  '确认', '是', '是的', '好的', '好', '继续', '执行', '确认执行', 'ok', 'yes',
  '取消', '否', '不要', '停止', 'no',
])

/** 回复「确认」或「取消」会接着执行已批准的计划，不能按普通首包时限掐断。 */
export function isWorkflowControlMessage(message: string): boolean {
  const text = String(message || '').trim().toLowerCase().replace(/[。.!！]+$/g, '')
  return WORKFLOW_CONTROL_WORDS.has(text)
}

export function isChatStreamEnabled(): boolean {
  const v = String(import.meta.env.VITE_CHAT_STREAM ?? '')
    .trim()
    .toLowerCase()
  if (v === '0' || v === 'false' || v === 'off' || v === 'no') return false
  return true
}

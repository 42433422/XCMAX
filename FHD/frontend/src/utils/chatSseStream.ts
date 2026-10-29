import { resolvePlannerChatStreamPath } from '@/utils/plannerChatPaths'

export type PlannerSseEvent =
  | { type: 'token'; text: string; ephemeral?: boolean }
  | { type: 'tool_progress'; label?: string; text?: string; phase?: string; run_id?: string }
  | { type: 'done'; result?: unknown }
  | { type: 'error'; message?: string; status_code?: number; run_id?: string }
  | { type: 'requires_token'; token_name?: string; token_description?: string; run_id?: string }

export class IncompletePlannerSseError extends Error {
  constructor() {
    super('连接提前结束，尚未收到完成回执。请核对原任务状态，勿重复提交可能已执行的操作。')
    this.name = 'IncompletePlannerSseError'
  }
}

function parseSseDataLine(line: string): PlannerSseEvent | null {
  const s = line.trim()
  if (!s.startsWith('data:')) return null
  const jsonStr = s.slice(5).trim()
  if (!jsonStr) return null
  try {
    return JSON.parse(jsonStr) as PlannerSseEvent
  } catch {
    return null
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
  let buffer = ''
  let terminalError = false
  let completed = false
  const emitLine = (line: string) => {
    const ev = parseSseDataLine(line)
    if (ev) {
      terminalError = ev.type === 'error'
      // The backend may end with an explicit authorization pause. Progress
      // after either receipt still requires a new terminal event before EOF.
      completed = ev.type === 'done' || ev.type === 'requires_token'
      onEvent(ev)
    }
    return terminalError
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (signal?.aborted) throw new DOMException('请求已中断', 'AbortError')
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        for (const line of part.split('\n')) {
          if (emitLine(line)) return
        }
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) {
      for (const line of buffer.split('\n')) {
        if (emitLine(line)) return
      }
    }
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

export function isChatStreamEnabled(): boolean {
  const v = String(import.meta.env.VITE_CHAT_STREAM ?? '')
    .trim()
    .toLowerCase()
  if (v === '0' || v === 'false' || v === 'off' || v === 'no') return false
  return true
}

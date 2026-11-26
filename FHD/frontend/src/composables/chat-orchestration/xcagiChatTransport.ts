import type { UIMessage, UIMessageChunk } from 'ai'
import chatApi, { parseChatStreamErrorResponse } from '@/api/chat'
import type { ChatRequest } from '@/types/chat'
import { readPlannerSseResponse, type PlannerSseEvent } from '@/utils/chatSseStream'
import { normalizeChatTraceItems, type ChatTraceItem } from './chatOrchestrationShared'
import type { ExecutionObservation } from '@/api/agentRuns'
import { readExecutionObservation } from '@/utils/agentRunTraceModel'

export interface XcagiChatMetadata {
  turnId?: string
  route?: unknown
  done?: unknown
  requiresToken?: { name: string; description: string }
}

export type XcagiUIMessage = UIMessage<XcagiChatMetadata>

export interface XcagiChatTransportOptions {
  /** 原始事件旁路：控制面（401/超时/授权/EOF）仍由调用方判定 */
  onEvent?: (event: PlannerSseEvent, seq: number) => void
  /** 本轮工具执行轨迹（正文之前的 ``trace`` 事件） */
  onTrace?: (items: ChatTraceItem[], seq: number) => void
  /** 传送层异常原样交回调用方，避免被框架改写身份 */
  onStreamError?: (error: unknown) => void
  /** Actual opaque SSE cursor, not the connection-local UI sequence. */
  onCursor?: (id: string) => void
}

const TEXT_ID = 'text-1'

/**
 * 把后端 SSE 翻译成 AI SDK 的 UIMessageChunk。
 *
 * 文本、工具进度、授权暂停都进入同一条 message 的 parts，顺序由事件到达顺序保证；
 * 异常不会抛给消费方，而是通过 ``onStreamError`` 原样交回控制面，再正常关闭流。
 */
export function createXcagiChatTransport(options: XcagiChatTransportOptions) {
  async function buildStream(fetchStream: () => Promise<Response>, signal?: AbortSignal, after?: string) {
    let response: Response
    try {
      response = await fetchStream()
    } catch (error) {
      options.onStreamError?.(error)
      return terminalStream(error instanceof Error ? error.message : '流式对话失败')
    }
    if (!response.ok) {
      const error = Object.assign(new Error(await parseChatStreamErrorResponse(response)), {
        status: response.status,
      })
      options.onStreamError?.(error)
      return terminalStream(error.message)
    }
    return translate(response, signal, after)
  }

  /** 连接都没建立：只吐一个错误就结束，保证消费方一定 settle。 */
  function terminalStream(message: string): ReadableStream<UIMessageChunk> {
    return new ReadableStream({
      start(controller) {
        controller.enqueue({ type: 'start' })
        controller.enqueue({ type: 'error', errorText: message })
        controller.enqueue({ type: 'finish' })
        controller.close()
      },
    })
  }

  function translate(response: Response, signal?: AbortSignal, after?: string): ReadableStream<UIMessageChunk> {
    return new ReadableStream<UIMessageChunk>({
      async start(controller) {
        let seq = 0
        const toolCalls = new Map<string, ExecutionObservation>()
        controller.enqueue({ type: 'start' })
        controller.enqueue({ type: 'start-step' })
        controller.enqueue({ type: 'text-start', id: TEXT_ID })
        try {
          await readPlannerSseResponse(
            response,
            (event) => {
              seq += 1
              applyEvent(controller, event, seq, toolCalls)
            },
            signal,
            { after, onCursor: options.onCursor },
          )
        } catch (error) {
          options.onStreamError?.(error)
          controller.enqueue({
            type: 'error',
            errorText: error instanceof Error ? error.message : String(error),
          })
        } finally {
          controller.enqueue({ type: 'text-end', id: TEXT_ID })
          controller.enqueue({ type: 'finish-step' })
          controller.enqueue({ type: 'finish' })
          try {
            controller.close()
          } catch {
            /* 已关闭 */
          }
        }
      },
    })
  }

  function applyEvent(
    controller: ReadableStreamDefaultController<UIMessageChunk>,
    event: PlannerSseEvent,
    seq: number,
    toolCalls: Map<string, ExecutionObservation>,
  ): void {
    options.onEvent?.(event, seq)
    if (event.type === 'token') {
      if (!event.ephemeral && event.text) {
        controller.enqueue({ type: 'text-delta', id: TEXT_ID, delta: event.text })
      }
      return
    }
    if (event.type === 'tool_progress') {
      controller.enqueue({ type: 'data-run-progress', id: 'run-progress', data: event })
      return
    }
    if (event.type === 'tool_call') {
      const id = String(event.node_id || '').trim()
      if (!id) return
      const observation = { ...(event.phase === 'started' ? {} : toolCalls.get(id)), ...readExecutionObservation({ ...event }) }
      // Compatibility ends here: the SDK owns each tool's input/output state.
      // A reconnect can begin with progress or a receipt, so seed its input once.
      if (event.phase === 'started' || !toolCalls.has(id)) {
        controller.enqueue({
          type: 'tool-input-available', toolCallId: id,
          toolName: [event.tool_id || 'tool', event.action].filter(Boolean).join('.'),
          input: event.params || {}, dynamic: true,
        })
      }
      toolCalls.set(id, observation)
      controller.enqueue({ type: 'data-tool-progress', id, data: { ...observation, ...event } })
      if (event.phase === 'finished') {
        const deferred = event.deferred === true && event.requires_reconciliation !== true
        controller.enqueue(event.success || deferred
          ? { type: 'tool-output-available', toolCallId: id, output: event.output_preview || (deferred ? event.error : '') || '' }
          : { type: 'tool-output-error', toolCallId: id, errorText: event.error || '工具执行失败' })
      }
      return
    }
    if (event.type === 'route_metadata') {
      controller.enqueue({ type: 'message-metadata', messageMetadata: { route: event.route_metadata } })
      return
    }
    if (event.type === 'trace') {
      // 轨迹只透出给回调（挂到当前 assistant 消息），不改变正文 parts。
      const items = normalizeChatTraceItems(event.items)
      if (items.length) options.onTrace?.(items, seq)
      return
    }
    if (event.type === 'requires_token') {
      const requiresToken = {
        name: event.token_name || '',
        description: event.token_description || '',
      }
      controller.enqueue({ type: 'data-requires-token', data: requiresToken })
      controller.enqueue({ type: 'message-metadata', messageMetadata: { requiresToken } })
      return
    }
    if (event.type === 'done') {
      controller.enqueue({ type: 'message-metadata', messageMetadata: { done: event.result } })
    }
  }

  return {
    async sendMessages(arg: { abortSignal?: AbortSignal; body?: object }) {
      return buildStream(() => chatApi.sendChatStream((arg.body || {}) as ChatRequest & Record<string, unknown>, { signal: arg.abortSignal }), arg.abortSignal)
    },
    async reconnectToStream(turnId: string, signal?: AbortSignal, after?: string) {
      return buildStream(() => after ? chatApi.resumeChatStream(turnId, signal, after) : chatApi.resumeChatStream(turnId, signal), signal, after)
    },
  }
}

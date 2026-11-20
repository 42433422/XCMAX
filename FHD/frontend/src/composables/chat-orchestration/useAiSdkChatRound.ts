import { readUIMessageStream } from 'ai'
import { ref } from 'vue'
import type { PlannerSseEvent } from '@/utils/chatSseStream'
import { createXcagiChatTransport, type XcagiUIMessage } from './xcagiChatTransport'
import type { ChatTraceItem } from './chatOrchestrationShared'

export interface AiSdkChatRoundOptions {
  onEvent?: (event: PlannerSseEvent, seq: number) => void
  onTrace?: (items: ChatTraceItem[], seq: number) => void
  onText?: (text: string) => void
  /** SDK 原生工具状态和 data parts；没有新增正文时也会更新。 */
  onMessage?: (message: XcagiUIMessage) => void
}

export interface AiSdkChatRoundResult {
  text: string
  lastSeq: number
  error: unknown | null
  aborted: boolean
}

function textFromMessage(message: XcagiUIMessage | undefined): string {
  if (!message || !Array.isArray(message.parts)) return ''
  return message.parts
    .filter((part) => part.type === 'text')
    .map((part) => (part as { text: string }).text)
    .join('')
}

/**
 * 用 AI SDK 的 ``readUIMessageStream`` 承担消息组装（parts 顺序、文本累加、
 * 同一 message 内去重），但请求生命周期由调用方控制：
 * 传送层异常通过 ``onStreamError`` 原样交回，不依赖框架回调时序。
 */
export function useAiSdkChatRound(options: AiSdkChatRoundOptions) {
  const text = ref('')
  let streamError: unknown = null
  let lastSeq = 0

  const transport = createXcagiChatTransport({
    onEvent: (event, seq) => {
      if (seq) lastSeq = seq
      options.onEvent?.(event, seq)
    },
    onTrace: (items, seq) => {
      options.onTrace?.(items, seq)
    },
    onStreamError: (error) => {
      streamError = error
    },
  })

  async function read(
    fetchStream: () => ReturnType<typeof transport.sendMessages>,
    signal?: AbortSignal,
  ): Promise<AiSdkChatRoundResult> {
    streamError = null
    lastSeq = 0
    text.value = ''
    let finalText = ''
    try {
      const stream = await fetchStream()
      for await (const message of readUIMessageStream<XcagiUIMessage>({
        stream,
        onError: (error) => {
          if (!streamError) streamError = error
        },
      })) {
        options.onMessage?.(message)
        const value = textFromMessage(message)
        if (value === finalText) continue
        finalText = value
        text.value = value
        options.onText?.(value)
      }
    } catch (error) {
      if (!streamError) streamError = error
    }
    return { text: finalText, lastSeq, error: streamError, aborted: Boolean(signal?.aborted) }
  }

  return {
    send: (body: Record<string, unknown>, signal?: AbortSignal) =>
      read(() => transport.sendMessages({ body, abortSignal: signal }), signal),
    resume: (turnId: string, signal?: AbortSignal) =>
      read(() => transport.reconnectToStream(turnId, signal), signal),
    text,
  }
}

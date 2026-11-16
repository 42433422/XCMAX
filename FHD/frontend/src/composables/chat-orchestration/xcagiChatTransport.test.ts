import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { UIMessageChunk } from 'ai'
import { createXcagiChatTransport } from './xcagiChatTransport'

const { sendChatStream } = vi.hoisted(() => ({ sendChatStream: vi.fn() }))

vi.mock('@/api/chat', () => ({
  default: { sendChatStream },
  parseChatStreamErrorResponse: vi.fn(async () => '流式请求失败'),
}))

function sseResponse(events: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const text = events.map((event) => `data: ${event}\n\n`).join('')
      controller.enqueue(new TextEncoder().encode(text))
      controller.close()
    },
  })
  return { ok: true, status: 200, body } as unknown as Response
}

async function drain(stream: ReadableStream<UIMessageChunk>): Promise<UIMessageChunk[]> {
  const chunks: UIMessageChunk[] = []
  const reader = stream.getReader()
  while (true) {
    const { done, value } = await reader.read()
    if (done) return chunks
    chunks.push(value)
  }
}

describe('xcagiChatTransport trace event', () => {
  beforeEach(() => {
    sendChatStream.mockReset()
  })

  it('把 trace 条目归一化后交给 onTrace，且不影响正文文本', async () => {
    const onTrace = vi.fn()
    sendChatStream.mockResolvedValueOnce(
      sseResponse([
        JSON.stringify({
          type: 'trace',
          items: [
            { tool: 'read_slice', args: { artifact_id: 'a1', sheet: 'Sheet1' }, ok: true, ms: 12, summary: '读取 3 行' },
            { tool: 'list_attachments', ok: false, ms: '9' },
            { tool: '', ok: true, ms: 1 },
          ],
          turn_id: 'turn-1',
        }),
        JSON.stringify({ type: 'token', text: '你好' }),
      ]),
    )
    const transport = createXcagiChatTransport({ onTrace })

    const chunks = await drain(await transport.sendMessages({ body: { message: 'hi' } }))

    expect(onTrace).toHaveBeenCalledTimes(1)
    expect(onTrace.mock.calls[0][0]).toEqual([
      { tool: 'read_slice', args: { artifact_id: 'a1', sheet: 'Sheet1' }, ok: true, ms: 12, summary: '读取 3 行' },
      { tool: 'list_attachments', ok: false, ms: 9 },
    ])
    expect(chunks).toContainEqual({ type: 'text-delta', id: 'text-1', delta: '你好' })
    expect(chunks.filter((chunk) => chunk.type === 'text-delta')).toHaveLength(1)
  })

  it('空 items 不触发 onTrace；未传 onTrace 也保持兼容', async () => {
    const onTrace = vi.fn()
    sendChatStream
      .mockResolvedValueOnce(sseResponse([JSON.stringify({ type: 'trace', items: [] })]))
      .mockResolvedValueOnce(sseResponse([JSON.stringify({ type: 'trace', items: [{ tool: 'x', ok: true, ms: 1 }] })]))
    const withCallback = createXcagiChatTransport({ onTrace })

    await drain(await withCallback.sendMessages({ body: {} }))
    expect(onTrace).not.toHaveBeenCalled()

    const legacy = createXcagiChatTransport({})
    await expect(drain(await legacy.sendMessages({ body: {} }))).resolves.toBeInstanceOf(Array)
  })
})

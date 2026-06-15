import { describe, it, expect } from 'vitest'
import { readPlannerSseResponse, isChatStreamEnabled } from './chatSseStream'

function mockSseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  let i = 0
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i >= chunks.length) {
        controller.close()
        return
      }
      controller.enqueue(encoder.encode(chunks[i]))
      i += 1
    },
  })
  return new Response(stream)
}

describe('chatSseStream', () => {
  it('readPlannerSseResponse parses token and done events', async () => {
    const events: string[] = []
    await readPlannerSseResponse(
      mockSseResponse(['data: {"type":"token","text":"你"}\n\n', 'data: {"type":"done","result":{"response":"你好"}}\n\n']),
      (ev) => events.push(ev.type),
    )
    expect(events).toEqual(['token', 'done'])
  })

  it('readPlannerSseResponse throws when body missing', async () => {
    await expect(readPlannerSseResponse(new Response(null), () => {})).rejects.toThrow(/不可读/)
  })

  it('isChatStreamEnabled respects VITE_CHAT_STREAM off', () => {
    const prev = import.meta.env.VITE_CHAT_STREAM
    import.meta.env.VITE_CHAT_STREAM = '0'
    try {
      expect(isChatStreamEnabled()).toBe(false)
    } finally {
      import.meta.env.VITE_CHAT_STREAM = prev
    }
  })
})

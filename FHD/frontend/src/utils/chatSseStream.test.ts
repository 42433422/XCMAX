import { describe, it, expect } from 'vitest'
import { readPlannerSseResponse, isChatStreamEnabled, resolveChatStreamPath } from './chatSseStream'
import { resolvePlannerChatStreamPath } from './plannerChatPaths'

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

  it('isChatStreamEnabled treats other off tokens as disabled', () => {
    const prev = import.meta.env.VITE_CHAT_STREAM
    try {
      for (const token of ['false', 'off', 'no']) {
        import.meta.env.VITE_CHAT_STREAM = token
        expect(isChatStreamEnabled()).toBe(false)
      }
    } finally {
      import.meta.env.VITE_CHAT_STREAM = prev
    }
  })

  it('isChatStreamEnabled is enabled when env var is missing', () => {
    const prev = import.meta.env.VITE_CHAT_STREAM
    import.meta.env.VITE_CHAT_STREAM = undefined
    try {
      expect(isChatStreamEnabled()).toBe(true)
    } finally {
      import.meta.env.VITE_CHAT_STREAM = prev
    }
  })

  it('resolveChatStreamPath delegates to the planner stream path resolver', () => {
    expect(resolveChatStreamPath()).toBe(resolvePlannerChatStreamPath())
  })

  it('ignores non-data lines and empty payloads in the stream', async () => {
    const events: string[] = []
    await readPlannerSseResponse(
      mockSseResponse(['event: message\nid: 1\n\n', 'data:\n\n', 'data: {"type":"token","text":"x"}\n\n']),
      (ev) => events.push(ev.type),
    )
    expect(events).toEqual(['token'])
  })

  it('ignores malformed JSON payloads', async () => {
    const events: string[] = []
    await readPlannerSseResponse(mockSseResponse(['data: {oops not json}\n\n', 'data: {"type":"done"}\n\n']), (ev) => events.push(ev.type))
    expect(events).toEqual(['done'])
  })

  it('flushes a trailing buffer without a closing separator', async () => {
    const events: string[] = []
    await readPlannerSseResponse(mockSseResponse(['data: {"type":"token","text":"a"}\n\n', 'data: {"type":"done","result":1}']), (ev) =>
      events.push(ev.type),
    )
    expect(events).toEqual(['token', 'done'])
  })

  it('surfaces error events verbatim', async () => {
    const events: Array<{ type: string; message?: string }> = []
    await readPlannerSseResponse(mockSseResponse(['data: {"type":"error","message":"boom"}\n\n']), (ev) => events.push(ev))
    expect(events[0]).toMatchObject({ type: 'error', message: 'boom' })
  })
})

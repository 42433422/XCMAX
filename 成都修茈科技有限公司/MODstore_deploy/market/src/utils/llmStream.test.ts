import { describe, it, expect, beforeEach, vi } from 'vitest'

const { llmChatStreamMock, llmChatMock } = vi.hoisted(() => ({
  llmChatStreamMock: vi.fn(),
  llmChatMock: vi.fn(),
}))

vi.mock('../api', () => ({
  api: {
    llmChatStream: llmChatStreamMock,
    llmChat: llmChatMock,
  },
}))

vi.mock('./llmBillingRefresh', () => ({
  refreshLevelAndWalletAfterLlm: vi.fn(),
}))

import { streamLLMChat, type StreamOptions } from './llmStream'

function makeSseResponse(frames: string[], status = 200): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    start(controller) {
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame))
      }
      controller.close()
    },
  })
  return new Response(stream, {
    status,
    headers: { 'content-type': 'text/event-stream' },
  })
}

function makeOpts(overrides: Partial<StreamOptions> = {}): StreamOptions {
  return {
    provider: 'openai',
    model: 'gpt-4',
    messages: [{ role: 'user', content: 'hi' }],
    onToken: vi.fn(),
    ...overrides,
  }
}

describe('streamLLMChat', () => {
  beforeEach(() => {
    llmChatStreamMock.mockReset()
    llmChatMock.mockReset()
  })

  it('streams SSE delta events and returns full content', async () => {
    const frames = [
      'event: delta\ndata: {"delta":"Hello"}\n\n',
      'event: delta\ndata: {"delta":" world"}\n\n',
      'event: done\ndata: {"content":"Hello world"}\n\n',
    ]
    llmChatStreamMock.mockResolvedValueOnce(makeSseResponse(frames))
    const onToken = vi.fn()
    const onDone = vi.fn()

    const handle = streamLLMChat({ ...makeOpts(), onToken, onDone })
    const result = await handle.done

    expect(result.content).toBe('Hello world')
    expect(result.aborted).toBe(false)
    expect(onToken).toHaveBeenCalledWith('Hello', 'Hello')
    expect(onToken).toHaveBeenCalledWith(' world', 'Hello world')
    expect(onDone).toHaveBeenCalledWith('Hello world', false)
  })

  it('handles meta event with billed flag', async () => {
    const frames = [
      'event: meta\ndata: {"billed":true}\n\n',
      'event: delta\ndata: {"delta":"Hi"}\n\n',
      'event: done\ndata: {"content":"Hi"}\n\n',
    ]
    llmChatStreamMock.mockResolvedValueOnce(makeSseResponse(frames))
    const result = await streamLLMChat(makeOpts()).done
    expect(result.content).toBe('Hi')
  })

  it('handles done event with charge_amount', async () => {
    const frames = [
      'event: delta\ndata: {"delta":"text"}\n\n',
      'event: done\ndata: {"charge_amount":10}\n\n',
    ]
    llmChatStreamMock.mockResolvedValueOnce(makeSseResponse(frames))
    const result = await streamLLMChat(makeOpts()).done
    expect(result.content).toBe('text')
  })

  it('falls back to llmChat when SSE response is not ok', async () => {
    llmChatStreamMock.mockResolvedValueOnce(
      new Response('{"detail":"server error"}', { status: 500 }),
    )
    llmChatMock.mockResolvedValueOnce({ content: 'fallback reply' })

    const result = await streamLLMChat(makeOpts()).done

    expect(result.content).toBe('fallback reply')
    expect(result.aborted).toBe(false)
    expect(llmChatMock).toHaveBeenCalled()
  })

  it('falls back when SSE throws and returns typewriter content', async () => {
    llmChatStreamMock.mockRejectedValueOnce(new Error('network error'))
    llmChatMock.mockResolvedValueOnce({ content: 'typewriter text' })

    const onToken = vi.fn()
    const result = await streamLLMChat({ ...makeOpts(), onToken, intervalMs: 1 }).done

    expect(result.content).toBe('typewriter text')
    expect(onToken).toHaveBeenCalled()
  })

  it('returns （无回复） when fallback content is empty', async () => {
    llmChatStreamMock.mockRejectedValueOnce(new Error('fail'))
    llmChatMock.mockResolvedValueOnce({ content: '' })

    const result = await streamLLMChat({ ...makeOpts(), intervalMs: 1 }).done

    expect(result.content).toBe('（无回复）')
  })

  it('calls onError when both SSE and fallback fail', async () => {
    llmChatStreamMock.mockRejectedValueOnce(new Error('sse fail'))
    llmChatMock.mockRejectedValueOnce(new Error('fallback fail'))
    const onError = vi.fn()

    const handle = streamLLMChat({ ...makeOpts(), onError })

    await expect(handle.done).rejects.toThrow('fallback fail')
    expect(onError).toHaveBeenCalled()
  })

  it('returns aborted=true when abort is called before fallback completes', async () => {
    llmChatStreamMock.mockRejectedValueOnce(new Error('sse fail'))
    llmChatMock.mockImplementation(
      () => new Promise(() => {}),
    )
    const onDone = vi.fn()

    const handle = streamLLMChat({ ...makeOpts(), onDone })
    handle.abort()

    const result = await handle.done
    expect(result.aborted).toBe(true)
  })

  it('parses 401 error as login expired message', async () => {
    llmChatStreamMock.mockResolvedValueOnce(
      new Response('{"detail":"登录已过期"}', { status: 401 }),
    )
    llmChatMock.mockRejectedValueOnce(new Error('also fail'))
    const onError = vi.fn()

    const handle = streamLLMChat({ ...makeOpts(), onError })
    await expect(handle.done).rejects.toThrow()
  })

  it('handles SSE error event', async () => {
    const frames = ['event: error\ndata: {"error":"stream failed"}\n\n']
    llmChatStreamMock.mockResolvedValueOnce(makeSseResponse(frames))
    llmChatMock.mockResolvedValueOnce({ content: 'recovered' })

    const result = await streamLLMChat({ ...makeOpts(), intervalMs: 1 }).done
    expect(result.content).toBe('recovered')
  })

  it('throws when stream returns no content and is not aborted', async () => {
    llmChatStreamMock.mockResolvedValueOnce(makeSseResponse([]))
    llmChatMock.mockResolvedValueOnce({ content: 'fallback ok' })

    const result = await streamLLMChat({ ...makeOpts(), intervalMs: 1 }).done
    expect(result.content).toBe('fallback ok')
  })

  it('handles raw text SSE data (non-JSON)', async () => {
    const frames = ['event: delta\ndata: raw text chunk\n\n']
    llmChatStreamMock.mockResolvedValueOnce(makeSseResponse(frames))
    llmChatMock.mockResolvedValueOnce({ content: 'fb' })

    const result = await streamLLMChat({ ...makeOpts(), intervalMs: 1 }).done
    expect(typeof result.content).toBe('string')
  })

  it('abort clears the typewriter timer in fallback path', async () => {
    llmChatStreamMock.mockRejectedValueOnce(new Error('sse fail'))
    llmChatMock.mockResolvedValueOnce({ content: 'long text for typewriter' })

    const handle = streamLLMChat({ ...makeOpts(), intervalMs: 1 })
    handle.abort()
    const result = await handle.done
    expect(result.aborted).toBe(true)
  })
})

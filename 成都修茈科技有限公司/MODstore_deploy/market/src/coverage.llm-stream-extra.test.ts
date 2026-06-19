import { afterEach, describe, expect, it, vi } from 'vitest'

const mockApi = vi.hoisted(() => ({
  llmChatStream: vi.fn(),
  llmChat: vi.fn(),
}))
const mockRefreshLevelAndWalletAfterLlm = vi.hoisted(() => vi.fn())

vi.mock('./api', () => ({ api: mockApi }))
vi.mock('./utils/llmBillingRefresh', () => ({
  refreshLevelAndWalletAfterLlm: () => mockRefreshLevelAndWalletAfterLlm(),
}))

function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  return {
    ok: true,
    status: 200,
    body: new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    }),
    text: vi.fn(async () => ''),
  } as unknown as Response
}

afterEach(() => {
  mockApi.llmChatStream.mockReset()
  mockApi.llmChat.mockReset()
  mockRefreshLevelAndWalletAfterLlm.mockClear()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('llm stream extra coverage', () => {
  it('streams SSE delta/done frames and refreshes billing when charged', async () => {
    const { streamLLMChat } = await import('./utils/llmStream')
    mockApi.llmChatStream.mockResolvedValueOnce(streamResponse([
      'event: meta\ndata: {"billed":true}\n\n',
      'event: delta\ndata: {"delta":"你"}\n\n',
      'event: delta\ndata: {"delta":"好"}\n\n',
      'event: done\ndata: {"content":"你好啊","charge_amount":1}\n\n',
    ]))
    const onToken = vi.fn()
    const onDone = vi.fn()

    const handle = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      onToken,
      onDone,
    })

    await expect(handle.done).resolves.toEqual({ content: '你好啊', aborted: false })
    expect(onToken).toHaveBeenCalledWith('你', '你')
    expect(onToken).toHaveBeenCalledWith('好', '你好')
    expect(onToken).toHaveBeenCalledWith('啊', '你好啊')
    expect(onDone).toHaveBeenCalledWith('你好啊', false)
    expect(mockRefreshLevelAndWalletAfterLlm).toHaveBeenCalled()
  })

  it('falls back to non-stream chat for HTTP errors and typewriter-replays content', async () => {
    vi.useFakeTimers()
    const { streamLLMChat } = await import('./utils/llmStream')
    mockApi.llmChatStream.mockResolvedValueOnce({
      ok: false,
      status: 401,
      body: null,
      text: vi.fn(async () => JSON.stringify({ detail: '登录失效' })),
    })
    mockApi.llmChat.mockResolvedValueOnce({ content: 'fallback text' })
    const onToken = vi.fn()
    const onDone = vi.fn()

    const handle = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      intervalMs: 2,
      onToken,
      onDone,
    })
    await vi.advanceTimersByTimeAsync(100)

    await expect(handle.done).resolves.toEqual({ content: 'fallback text', aborted: false })
    expect(onToken).toHaveBeenCalled()
    expect(onDone).toHaveBeenCalledWith('fallback text', false)
  })

  it('reports fallback errors and normalizes aborts', async () => {
    const { streamLLMChat } = await import('./utils/llmStream')
    mockApi.llmChatStream.mockResolvedValueOnce(streamResponse([
      'event: error\ndata: {"error":"stream failed"}\n\n',
    ]))
    mockApi.llmChat.mockRejectedValueOnce(new Error('fallback failed'))
    const onError = vi.fn()

    const failed = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      onToken: vi.fn(),
      onError,
    })
    await expect(failed.done).rejects.toThrow('fallback failed')
    expect(onError).toHaveBeenCalled()

    mockApi.llmChatStream.mockImplementationOnce((_p, _m, _messages, _max, _cid, signal: AbortSignal) => ({
      ok: true,
      status: 200,
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('event: delta\ndata: {"delta":"慢"}\n\n'))
          signal.addEventListener('abort', () => controller.close())
        },
      }),
      text: vi.fn(async () => ''),
    }))
    const onDone = vi.fn()
    const aborted = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      onToken: vi.fn(),
      onDone,
    })
    aborted.abort()
    await expect(aborted.done).resolves.toEqual({ content: '（无回复）', aborted: true })
    expect(onDone).toHaveBeenCalledWith('（无回复）', true)
  })

  it('covers HTTP error parsing branches and fallback empty or long replies', async () => {
    vi.useFakeTimers()
    const { streamLLMChat } = await import('./utils/llmStream')

    mockApi.llmChatStream.mockResolvedValueOnce({
      ok: false,
      status: 503,
      body: null,
      text: vi.fn(async () => ''),
    })
    mockApi.llmChat.mockResolvedValueOnce({ content: '' })
    const emptyDone = vi.fn()
    const empty = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      intervalMs: -10,
      onToken: vi.fn(),
      onDone: emptyDone,
    })
    await vi.runAllTimersAsync()
    await expect(empty.done).resolves.toEqual({ content: '（无回复）', aborted: false })
    expect(emptyDone).toHaveBeenCalledWith('（无回复）', false)

    mockApi.llmChatStream.mockResolvedValueOnce({
      ok: false,
      status: 429,
      body: null,
      text: vi.fn(async () => JSON.stringify({ message: '排队中' })),
    })
    const longText = '长'.repeat(1301)
    mockApi.llmChat.mockResolvedValueOnce({ content: longText })
    const long = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      intervalMs: 500,
      onToken: vi.fn(),
    })
    await vi.runAllTimersAsync()
    await expect(long.done).resolves.toEqual({ content: longText, aborted: false })

    mockApi.llmChatStream.mockResolvedValueOnce({
      ok: false,
      status: 401,
      body: null,
      text: vi.fn(async () => '需要登录后继续'),
    })
    mockApi.llmChat.mockResolvedValueOnce({ content: 'raw login fallback' })
    const rawLogin = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      intervalMs: 2,
      onToken: vi.fn(),
    })
    await vi.runAllTimersAsync()
    await expect(rawLogin.done).resolves.toEqual({ content: 'raw login fallback', aborted: false })

    mockApi.llmChatStream.mockResolvedValueOnce({
      ok: false,
      status: 500,
      body: null,
      text: vi.fn(async () => JSON.stringify({ detail: '后端繁忙' })),
    })
    mockApi.llmChat.mockResolvedValueOnce({ content: 'detail fallback' })
    const detail = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      intervalMs: 2,
      onToken: vi.fn(),
    })
    await vi.runAllTimersAsync()
    await expect(detail.done).resolves.toEqual({ content: 'detail fallback', aborted: false })
  })

  it('covers SSE parser edge cases for empty events, empty deltas, and implicit final content', async () => {
    const { streamLLMChat } = await import('./utils/llmStream')
    mockApi.llmChatStream.mockResolvedValueOnce(streamResponse([
      'event:\n\n',
      'event: delta\ndata: {"delta":""}\n\n',
      'event: delta\ndata: {"delta":"A"}\n\n',
      'event: done\ndata: {}\n\n',
    ]))
    const onToken = vi.fn()
    const onDone = vi.fn()

    const handle = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      onToken,
      onDone,
    })

    await expect(handle.done).resolves.toEqual({ content: 'A', aborted: false })
    expect(onToken).toHaveBeenCalledTimes(1)
    expect(onToken).toHaveBeenCalledWith('A', 'A')
    expect(onDone).toHaveBeenCalledWith('A', false)
  })

  it('falls back after empty streams and raw SSE errors, then normalizes non-error fallback failures', async () => {
    const { streamLLMChat } = await import('./utils/llmStream')

    mockApi.llmChatStream.mockResolvedValueOnce(streamResponse([
      'event: meta\ndata: {"billed":false}\n\n',
    ]))
    mockApi.llmChat.mockRejectedValueOnce('fallback string failed')
    const onError = vi.fn()
    const emptyStream = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      onToken: vi.fn(),
      onError,
    })
    await expect(emptyStream.done).rejects.toThrow('fallback string failed')
    expect(onError).toHaveBeenCalled()

    vi.useFakeTimers()
    mockApi.llmChatStream.mockResolvedValueOnce(streamResponse([
      'event: error\ndata: plain stream failed\n\n',
    ]))
    mockApi.llmChat.mockResolvedValueOnce({ content: 'raw error fallback' })
    const rawError = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      intervalMs: 2,
      onToken: vi.fn(),
    })
    await vi.runAllTimersAsync()
    await expect(rawError.done).resolves.toEqual({ content: 'raw error fallback', aborted: false })
  })

  it('normalizes aborts before fallback output and while stream or fallback promises fail', async () => {
    const { streamLLMChat } = await import('./utils/llmStream')

    let beforeFallbackAbort: ReturnType<typeof streamLLMChat>
    mockApi.llmChatStream.mockRejectedValueOnce(new Error('stream down'))
    mockApi.llmChat.mockImplementationOnce(async () => {
      beforeFallbackAbort.abort()
      return { content: 'late fallback' }
    })
    beforeFallbackAbort = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      onToken: vi.fn(),
    })
    await expect(beforeFallbackAbort.done).resolves.toEqual({ content: '', aborted: true })

    let streamAbort: ReturnType<typeof streamLLMChat>
    mockApi.llmChatStream.mockImplementationOnce(
      () => new Promise((_resolve, reject) => {
        queueMicrotask(() => {
          streamAbort.abort()
          reject(new Error('late stream fail'))
        })
      }),
    )
    streamAbort = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      onToken: vi.fn(),
    })
    await expect(streamAbort.done).resolves.toEqual({ content: '', aborted: true })

    let fallbackAbort: ReturnType<typeof streamLLMChat>
    mockApi.llmChatStream.mockRejectedValueOnce(new Error('stream down'))
    mockApi.llmChat.mockImplementationOnce(
      () => new Promise((_resolve, reject) => {
        queueMicrotask(() => {
          fallbackAbort.abort()
          reject(new Error('late fallback fail'))
        })
      }),
    )
    fallbackAbort = streamLLMChat({
      provider: 'p',
      model: 'm',
      messages: [{ role: 'user', content: 'hi' }],
      onToken: vi.fn(),
    })
    await expect(fallbackAbort.done).resolves.toEqual({ content: '', aborted: true })
  })
})

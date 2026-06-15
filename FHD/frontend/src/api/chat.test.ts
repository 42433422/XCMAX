import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))
const sse = vi.hoisted(() => ({
  readPlannerSseResponse: vi.fn().mockResolvedValue(undefined),
  resolveChatStreamPath: vi.fn(() => '/api/ai/chat/stream'),
}))

vi.mock('./core', () => ({
  api: apiMock,
  default: apiMock,
  buildFullApiUrl: (u: string) => `http://x${u}`,
}))
vi.mock('@/utils/chatSseStream', () => ({
  readPlannerSseResponse: sse.readPlannerSseResponse,
  resolveChatStreamPath: sse.resolveChatStreamPath,
}))

import chatApi, { parseChatStreamErrorResponse } from './chat'

beforeEach(() => {
  apiMock.get.mockReset().mockResolvedValue({ success: true })
  apiMock.post.mockReset().mockResolvedValue({ success: true })
  sse.readPlannerSseResponse.mockClear()
  globalThis.fetch = vi.fn()
})

describe('chatApi thin wrappers', () => {
  it('covers post/get endpoints', async () => {
    await chatApi.sendChat({ message: 'hi' } as never)
    await chatApi.getContext({ user_id: 'u' })
    await chatApi.clearContext({ user_id: 'u' })
    await chatApi.getConfig()
    await chatApi.testIntent({ text: 't' })
    await chatApi.sendUnifiedChat({ message: 'hi' } as never)
    await chatApi.sendChatBatch({ messages: ['a', 'b'] } as never)
    await chatApi.sendUnifiedChatBatch({ messages: ['a'] } as never)
    await chatApi.getConversations({ page: 1 })
    await chatApi.clearConversations()
    await chatApi.getConversation('sid')
    await chatApi.saveMessage({ x: 1 })
    await chatApi.newConversation()
    expect(apiMock.post).toHaveBeenCalled()
    expect(apiMock.get).toHaveBeenCalledWith('/api/ai/context', { user_id: 'u' })
  })

  it('merges market authorization header when token present', async () => {
    window.localStorage.setItem('xcagi_market_access_token', 'abc')
    await chatApi.sendChat({ message: 'hi' } as never)
    const [, , options] = apiMock.post.mock.calls[0]
    expect((options as { headers: Record<string, string> }).headers.Authorization).toContain('Bearer')
    window.localStorage.removeItem('xcagi_market_access_token')
  })
})

describe('parseChatStreamErrorResponse', () => {
  it('extracts json message', async () => {
    const res = {
      status: 400,
      headers: { get: () => 'application/json' },
      json: async () => ({ message: '出错了' }),
    } as unknown as Response
    expect(await parseChatStreamErrorResponse(res)).toBe('出错了')
  })

  it('falls back to default on non-json', async () => {
    const res = {
      status: 500,
      headers: { get: () => 'text/plain' },
      json: async () => ({}),
    } as unknown as Response
    expect(await parseChatStreamErrorResponse(res)).toContain('500')
  })

  it('falls back when json throws', async () => {
    const res = {
      status: 502,
      headers: { get: () => 'application/json' },
      json: async () => {
        throw new Error('bad')
      },
    } as unknown as Response
    expect(await parseChatStreamErrorResponse(res)).toContain('502')
  })
})

describe('chatApi stream methods', () => {
  it('sendChatStream issues POST fetch', async () => {
    ;(globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ ok: true } as Response)
    await chatApi.sendChatStream({ message: 'hi' } as never)
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://x/api/ai/chat/stream',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('consumeChatStream reads sse when ok', async () => {
    ;(globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ ok: true } as Response)
    const onEvent = vi.fn()
    await chatApi.consumeChatStream({ message: 'hi' } as never, onEvent)
    expect(sse.readPlannerSseResponse).toHaveBeenCalled()
  })

  it('consumeChatStream throws on non-ok', async () => {
    ;(globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 503,
      headers: { get: () => 'text/plain' },
      json: async () => ({}),
    } as unknown as Response)
    await expect(chatApi.consumeChatStream({ message: 'hi' } as never, vi.fn())).rejects.toThrow()
  })
})

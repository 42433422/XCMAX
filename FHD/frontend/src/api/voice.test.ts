import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const apiMock = vi.hoisted(() => ({ post: vi.fn() }))
const primeCsrfCookie = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))
const buildFullApiUrl = vi.hoisted(() => (u: string) => `https://api.test${u}`)
const shouldAttachCsrfHeader = vi.hoisted(() => vi.fn().mockReturnValue(false))
const readCsrfTokenFromCookie = vi.hoisted(() => vi.fn().mockReturnValue(null))

vi.mock('./core', () => ({
  api: apiMock,
  default: apiMock,
  primeCsrfCookie,
  buildFullApiUrl,
}))

vi.mock('@/utils/csrfCookie', () => ({
  readCsrfTokenFromCookie,
  shouldAttachCsrfHeader,
}))

import voiceApi from './voice'

const okPayload = { success: true, data: { text: 'hello' } }

function makeBlob(type = 'audio/webm'): Blob {
  return new Blob([new Uint8Array([1, 2, 3])], { type })
}

beforeEach(() => {
  apiMock.post.mockReset().mockResolvedValue(okPayload)
  primeCsrfCookie.mockClear().mockResolvedValue(undefined)
  shouldAttachCsrfHeader.mockReturnValue(false)
  readCsrfTokenFromCookie.mockReturnValue(null)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('voiceApi.transcribeVoice', () => {
  it('primes csrf and posts FormData with default timeout', async () => {
    const result = await voiceApi.transcribeVoice(makeBlob())
    expect(primeCsrfCookie).toHaveBeenCalledOnce()
    expect(apiMock.post).toHaveBeenCalledOnce()
    const [url, body, opts] = apiMock.post.mock.calls.at(-1)!
    expect(url).toBe('/api/voice/transcribe')
    expect(body).toBeInstanceOf(FormData)
    expect((opts as { timeoutMs: number }).timeoutMs).toBe(60_000)
    expect(result).toEqual(okPayload)
  })

  it('passes language option through FormData and overrides timeout', async () => {
    await voiceApi.transcribeVoice(makeBlob('audio/wav'), {
      language: 'en',
      timeoutMs: 5_000,
    })
    const [, body, opts] = apiMock.post.mock.calls.at(-1)!
    const form = body as FormData
    expect(form.get('language')).toBe('en')
    expect((opts as { timeoutMs: number }).timeoutMs).toBe(5_000)
  })

  it('guesses audio extension from mime', async () => {
    const cases: Array<[string, string]> = [
      ['audio/webm', 'webm'],
      ['audio/ogg', 'ogg'],
      ['audio/mp4', 'm4a'],
      ['audio/x-m4a', 'm4a'],
      ['audio/wav', 'wav'],
      ['audio/wave', 'wav'],
      ['', 'bin'],
      ['application/octet-stream', 'bin'],
    ]
    for (const [mime, expected] of cases) {
      apiMock.post.mockClear()
      await voiceApi.transcribeVoice(makeBlob(mime))
      const [, body] = apiMock.post.mock.calls.at(-1)!
      const form = body as FormData
      const file = form.get('file') as File
      expect(file.name.endsWith(`.${expected}`)).toBe(true)
    }
  })
})

describe('voiceApi.voiceCommand', () => {
  function mockFetchOnce(body: unknown, ok = true, status = 200): void {
    const text = typeof body === 'string' ? body : JSON.stringify(body)
    vi.spyOn(window, 'fetch').mockResolvedValueOnce({
      ok,
      status,
      text: () => Promise.resolve(text),
    } as Response)
  }

  beforeEach(() => {
    vi.spyOn(window, 'fetch')
  })

  it('posts multipart form to /api/voice/command and returns parsed payload', async () => {
    mockFetchOnce(okPayload)
    const result = await voiceApi.voiceCommand(makeBlob())
    expect(primeCsrfCookie).toHaveBeenCalledOnce()
    expect(window.fetch).toHaveBeenCalledOnce()
    const [url, init] = (window.fetch as ReturnType<typeof vi.fn>).mock.calls.at(-1)!
    expect(url).toBe('https://api.test/api/voice/command')
    const opts = init as RequestInit
    expect(opts.method).toBe('POST')
    expect(opts.body).toBeInstanceOf(FormData)
    const form = opts.body as FormData
    expect(form.get('auto_execute')).toBe('false')
    expect(result).toEqual(okPayload)
  })

  it('appends session_id and language when provided', async () => {
    mockFetchOnce(okPayload)
    await voiceApi.voiceCommand(makeBlob(), {
      sessionId: 'sess-123',
      language: 'zh',
      autoExecute: true,
    })
    const [, init] = (window.fetch as ReturnType<typeof vi.fn>).mock.calls.at(-1)!
    const form = (init as RequestInit).body as FormData
    expect(form.get('session_id')).toBe('sess-123')
    expect(form.get('language')).toBe('zh')
    expect(form.get('auto_execute')).toBe('true')
  })

  it('attaches CSRF header when shouldAttachCsrfHeader returns true', async () => {
    shouldAttachCsrfHeader.mockReturnValue(true)
    readCsrfTokenFromCookie.mockReturnValue('csrf-tok')
    mockFetchOnce(okPayload)
    await voiceApi.voiceCommand(makeBlob())
    const [, init] = (window.fetch as ReturnType<typeof vi.fn>).mock.calls.at(-1)!
    const headers = (init as RequestInit).headers as Record<string, string>
    expect(headers['X-CSRF-Token']).toBe('csrf-tok')
  })

  it('throws when response is not ok', async () => {
    mockFetchOnce({ success: false, detail: 'bad' }, false, 400)
    await expect(voiceApi.voiceCommand(makeBlob())).rejects.toThrow('bad')
  })

  it('throws when payload.success is false (uses message if present)', async () => {
    mockFetchOnce({ success: false, message: 'no intent' })
    await expect(voiceApi.voiceCommand(makeBlob())).rejects.toThrow('no intent')
  })

  it('falls back to raw body when payload has no detail/message', async () => {
    mockFetchOnce('raw-text-error', false, 500)
    await expect(voiceApi.voiceCommand(makeBlob())).rejects.toThrow('raw-text-error')
  })

  it('falls back to HTTP status when body empty', async () => {
    mockFetchOnce('', false, 502)
    await expect(voiceApi.voiceCommand(makeBlob())).rejects.toThrow('HTTP 502')
  })

  it('treats non-JSON body as raw error', async () => {
    vi.spyOn(window, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 400,
      text: () => Promise.resolve('plain text'),
    } as Response)
    await expect(voiceApi.voiceCommand(makeBlob())).rejects.toThrow('plain text')
  })

  it('handles non-JSON body as raw error when response is ok but payload unparseable', async () => {
    // 不构造 ok=true 但 body 非 JSON 的情况（payload=null 会走 error 路径）
    mockFetchOnce('not-json', true, 200)
    await expect(voiceApi.voiceCommand(makeBlob())).rejects.toThrow('not-json')
  })
})

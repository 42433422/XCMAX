import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, registerSessionRefresh } from '@/api/core'

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (key: string) => (key.toLowerCase() === 'content-type' ? 'application/json' : null) },
    json: async () => body,
  } as unknown as Response
}

afterEach(() => {
  registerSessionRefresh(null)
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('api transport stability', () => {
  it('sends a request id and classifies a dropped connection as server unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
    await expect(api.get('/api/health', {}, { timeoutMs: 1000, retry: false })).rejects.toMatchObject({
      status: 0,
      message: expect.stringContaining('服务暂时不可用'),
      data: { success: false, stability: expect.objectContaining({ kind: 'server_down', success: false }) },
    })
    const init = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit
    expect(String((init.headers as Record<string, string>)['X-Request-ID']).length).toBeGreaterThanOrEqual(8)
  })

  it('classifies browser offline separately from a timeout', async () => {
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))
    await expect(api.post('/api/chat', { message: 'hi' }, { retry: false })).rejects.toMatchObject({
      message: expect.stringContaining('网络已断开'),
    })

    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    })))
    const pending = api.post('/api/erp/orders', { n: 1 }, { timeoutMs: 3_000, retry: false })
    const rejection = expect(pending).rejects.toMatchObject({
      message: expect.stringContaining('请求超时'),
      data: { success: false, stability: expect.objectContaining({ kind: 'timeout', success: false }) },
    })
    await vi.advanceTimersByTimeAsync(3_100)
    await rejection
  })

  it('refreshes once for concurrent 401s and surfaces re-login when refresh fails', async () => {
    let refreshCalls = 0
    let release!: (ok: boolean) => void
    registerSessionRefresh(() => new Promise<boolean>((resolve) => {
      refreshCalls += 1
      release = resolve
    }))
    let attempts = 0
    vi.stubGlobal('fetch', vi.fn(async () => {
      attempts += 1
      if (attempts < 4) return jsonResponse(401, { message: 'unauthorized' })
      return jsonResponse(200, { success: true })
    }))
    const pending = Promise.all([
      api.get('/api/system/a', {}, { retry: false }),
      api.get('/api/system/b', {}, { retry: false }),
      api.get('/api/desktop/c', {}, { retry: false }),
    ])
    await vi.waitFor(() => expect(refreshCalls).toBe(1))
    release(true)
    await expect(pending).resolves.toEqual([{ success: true }, { success: true }, { success: true }])
    expect(attempts).toBe(6)

    registerSessionRefresh(async () => false)
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(401, { message: 'unauthorized' })))
    await expect(api.get('/api/system/expired', {}, { retry: false })).rejects.toMatchObject({
      status: 401,
      message: expect.stringContaining('重新登录'),
    })
  })

  it('does not run a side effect twice when the first result is unknown', async () => {
    let calls = 0
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls += 1
      throw new TypeError('Failed to fetch')
    }))
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
    const options = { idempotencyKey: 'erp-write-1', sideEffect: true, retry: false }
    await expect(api.post('/api/erp/orders', { qty: 1 }, options)).rejects.toThrow('服务暂时不可用')
    await expect(api.post('/api/erp/orders', { qty: 1 }, options)).rejects.toThrow('结果未知')
    expect(calls).toBe(1)
  })
})

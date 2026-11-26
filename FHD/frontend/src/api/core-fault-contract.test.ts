import { afterEach, describe, expect, it, vi } from 'vitest'
import api from './core'
import { noteTransportSuccess } from '@/utils/networkStability'

vi.mock('@/utils/apiBase', () => ({ getApiBase: () => '' }))
vi.mock('@/utils/erpDomainPaths', () => ({ resolveErpApiPathWhenReady: async (path: string) => path }))
vi.mock('@/utils/clientShell', () => ({ clientShellRequestHeaders: () => ({}) }))
vi.mock('@/utils/adminConsoleUrl', () => ({ isAdminConsoleSpa: () => false }))
vi.mock('@/utils/productReadAccountScope', () => ({ productReadAccountEpoch: { value: 0 } }))

function success() {
  return new Response('{"success":true}', { status: 200, headers: { 'content-type': 'application/json' } })
}
function requestId(fetcher: ReturnType<typeof vi.fn>, index = 0) {
  return new Headers(fetcher.mock.calls[index][1].headers).get('x-request-id')
}
afterEach(() => {
  noteTransportSuccess()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('public API transport fault and correlation contract', () => {
  it('retries a failed read once and returns only the recovered server result', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValueOnce(success())
    vi.stubGlobal('fetch', fetcher)
    await expect(api.get('/api/health', {}, { quiet: true })).resolves.toEqual({ success: true })
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(requestId(fetcher, 0)).toBeTruthy()
    expect(requestId(fetcher, 1)).toBeTruthy()
  })

  it('does not replay an ambiguous write automatically, including a repeated user submission', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValueOnce(success())
    vi.stubGlobal('fetch', fetcher)
    const options = { idempotencyKey: 'fault-contract-ambiguous-write', sideEffect: true, quiet: true }
    const payload = { value: 1 }
    await expect(api.post('/api/fault-contract/write', payload, options)).rejects.toMatchObject({ status: 0 })
    expect(fetcher).toHaveBeenCalledTimes(1)
    await expect(api.post('/api/fault-contract/write', payload, options)).rejects.toThrow('结果未知')
    expect(fetcher).toHaveBeenCalledTimes(1)
    await expect(api.post('/api/fault-contract/write', payload, { ...options, confirmUnknownRetry: true })).resolves.toEqual({ success: true })
    expect(fetcher).toHaveBeenCalledTimes(2)
    for (const [, init] of fetcher.mock.calls) {
      expect(new Headers(init.headers).get('idempotency-key')).toBe(options.idempotencyKey)
    }
  })

  it('reports timeout as failure and retains the actual attempted request ID', async () => {
    const fetcher = vi.fn((_url, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
      const abort = () => reject(new DOMException('aborted', 'AbortError'))
      if (init.signal?.aborted) abort()
      else init.signal?.addEventListener('abort', abort, { once: true })
    }))
    vi.stubGlobal('fetch', fetcher)
    const result = api.get('/api/health', {}, { timeoutMs: 20, retry: false, quiet: true })
    const failure = await result.catch(error => error)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(requestId(fetcher)).toBeTruthy()
    expect(failure).toMatchObject({ name: 'ApiError', status: 0, requestId: requestId(fetcher), data: { stability: { kind: 'timeout', success: false } } })
  })

  it('keeps a definitive authorization error correlated without replaying it', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{"message":"denied"}', { status: 403, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetcher)
    const failure = await api.get('/api/health', {}, { headers: { 'x-request-id': 'explicit-trace' }, quiet: true }).catch(error => error)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(requestId(fetcher)).toBe('explicit-trace')
    expect(failure).toMatchObject({ name: 'ApiError', status: 403, requestId: 'explicit-trace', data: { message: 'denied' } })
  })
})

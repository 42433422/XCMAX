import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '@/api/core'

function makeResponse(opts: { ok?: boolean; status?: number; json?: unknown }) {
  const { ok = true, status = 200, json } = opts
  return {
    ok,
    status,
    headers: { get: (k: string) => (k.toLowerCase() === 'content-type' ? 'application/json' : null) },
    json: async () => json,
  } as unknown as Response
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  delete (window as unknown as { __XCMAX_API_BASE__?: string }).__XCMAX_API_BASE__
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function captureReachableEvents(): { events: CustomEvent[]; stop: () => void } {
  const events: CustomEvent[] = []
  const listener = (event: Event) => events.push(event as CustomEvent)
  window.addEventListener('xcagi:api-reachable', listener)
  return { events, stop: () => window.removeEventListener('xcagi:api-reachable', listener) }
}

describe('侧边栏健康状态的服务可达信号', () => {
  it('任意接口成功都通知服务可连接，且按节流只通知一次', async () => {
    const { events, stop } = captureReachableEvents()
    fetchMock.mockResolvedValue(makeResponse({ json: { success: true } }))
    await api.get('/api/desktop/status')
    await api.get('/api/desktop/status')
    stop()
    expect(events).toHaveLength(1)
    expect(events[0].detail.source).toBe('api')
  })

  it('接口返回错误状态码也证明服务可连接', async () => {
    const { events, stop } = captureReachableEvents()
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 60_000)
    fetchMock.mockResolvedValue(makeResponse({ ok: false, status: 404, json: { message: 'not found' } }))
    await expect(api.get('/api/desktop/status')).rejects.toBeInstanceOf(ApiError)
    stop()
    expect(events).toHaveLength(1)
  })
})

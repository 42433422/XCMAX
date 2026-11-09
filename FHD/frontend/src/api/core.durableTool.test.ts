import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/erpDomainPaths', () => ({
  resolveErpApiPathWhenReady: async (url: string) => url,
}))

import api from './core'

describe('durable office ELT requests', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('does not abort office confirm at 8s or when the chat signal aborts', async () => {
    vi.useFakeTimers()
    const caller = new AbortController()
    let finish: (response: Response) => void = () => {}
    const fetchMock = vi.fn((_url: string, init: RequestInit) => new Promise<Response>((resolve) => {
      finish = resolve
      init.signal?.addEventListener('abort', () => {
        resolve(new Response('aborted', { status: 499 }))
      })
    }))
    vi.stubGlobal('fetch', fetchMock)
    const pending = api.post(
      '/api/platform-shell/office/confirm',
      { intent: 'elt_save' },
      { timeoutMs: 8_000, signal: caller.signal },
    )
    caller.abort()
    await vi.advanceTimersByTimeAsync(9_000)
    const signal = fetchMock.mock.calls[0][1].signal as AbortSignal | undefined
    expect(signal?.aborted).not.toBe(true)
    finish(new Response(JSON.stringify({ success: true, data: { status: 'awaiting_approval' } }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }))
    await expect(pending).resolves.toMatchObject({ success: true })
  })
})

import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/erpDomainPaths', () => ({
  resolveErpApiPathWhenReady: async (url: string) => url,
}))

import api, { AccountSwitchedError } from './core'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

function deferredJsonResponse() {
  let resolve!: () => void
  const gate = new Promise<void>(r => { resolve = r })
  const fetchMock = vi.fn(async () => {
    await gate
    return new Response(JSON.stringify({ success: true, data: ['tenant-a'] }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return resolve
}

describe('api core account switch guard', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('discards a response that lands after the account switched', async () => {
    const release = deferredJsonResponse()
    const pending = api.get('/api/orders')
    await Promise.resolve()
    productReadAccountEpoch.value++
    release()
    await expect(pending).rejects.toBeInstanceOf(AccountSwitchedError)
  })

  it('keeps auth responses that drive the switch', async () => {
    const release = deferredJsonResponse()
    const pending = api.get('/api/auth/profile')
    await Promise.resolve()
    productReadAccountEpoch.value++
    release()
    await expect(pending).resolves.toMatchObject({ success: true })
  })

  it('returns responses when the account is unchanged', async () => {
    const release = deferredJsonResponse()
    release()
    await expect(api.get('/api/orders')).resolves.toMatchObject({ data: ['tenant-a'] })
  })

  it('does not start the second read after the caller aborts during backoff', async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    let rejectFetch!: (error: Error) => void
    const gate = new Promise<Response>((_resolve, reject) => { rejectFetch = reject })
    const fetchMock = vi.fn(() => gate)
    vi.stubGlobal('fetch', fetchMock)
    const pending = api.get('/api/orders', {}, { signal: controller.signal })
    let captured: unknown
    const settled = pending.then(() => { throw new Error('read should fail') }, (error: unknown) => { captured = error })
    await Promise.resolve()
    await Promise.resolve()
    rejectFetch(new TypeError('Failed to fetch'))
    await vi.advanceTimersByTimeAsync(0)
    controller.abort()
    await vi.advanceTimersByTimeAsync(250)
    await settled
    expect(captured).toMatchObject({ status: 0, message: '服务暂时不可用。请稍后重试，无需重新登录。' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('drops the retry when the account changes during backoff', async () => {
    vi.useFakeTimers()
    let rejectFetch!: (error: Error) => void
    const gate = new Promise<Response>((_resolve, reject) => { rejectFetch = reject })
    const fetchMock = vi.fn(() => gate)
    vi.stubGlobal('fetch', fetchMock)
    const pending = api.get('/api/orders')
    let captured: unknown
    const settled = pending.then(() => { throw new Error('read should fail') }, (error: unknown) => { captured = error })
    await Promise.resolve()
    await Promise.resolve()
    rejectFetch(new TypeError('Failed to fetch'))
    await vi.advanceTimersByTimeAsync(0)
    productReadAccountEpoch.value++
    await vi.advanceTimersByTimeAsync(250)
    await settled
    expect(captured).toBeInstanceOf(AccountSwitchedError)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('aborts a budgeted read immediately when the caller signal is already aborted', async () => {
    const controller = new AbortController()
    controller.abort()
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.signal?.aborted) throw init.signal.reason ?? new DOMException('aborted', 'AbortError')
      return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })
    }))
    await expect(api.get('/api/orders', {}, { timeoutMs: 1_000, signal: controller.signal })).rejects.toBeTruthy()
  })

  it('skips the automatic read retry when the caller set an explicit budget', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ message: 'down' }), {
      status: 503,
      headers: { 'content-type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const pending = api.get('/api/orders', {}, { retry: false })
    const rejection = expect(pending).rejects.toMatchObject({ status: 503 })
    await vi.advanceTimersByTimeAsync(1_000)
    await rejection
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not retry a read into the new account after a network failure', async () => {
    let rejectFetch!: (error: Error) => void
    const gate = new Promise<Response>((_resolve, reject) => { rejectFetch = reject })
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => gate)
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: true, data: ['tenant-b'] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const pending = api.get('/api/orders')
    await Promise.resolve()
    await Promise.resolve()
    productReadAccountEpoch.value++
    rejectFetch(new TypeError('network down'))
    await expect(pending).rejects.toBeInstanceOf(AccountSwitchedError)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

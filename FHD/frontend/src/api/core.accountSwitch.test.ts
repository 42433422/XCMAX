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

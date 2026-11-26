import { afterEach, describe, expect, it, vi } from 'vitest'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

const route = vi.hoisted(() => vi.fn())
vi.mock('@/utils/erpDomainPaths', () => ({ resolveErpApiPathWhenReady: route }))
vi.mock('@/utils/apiBase', () => ({ getApiBase: () => 'http://localhost:5001' }))

import { api, AccountSwitchedError } from './core'

afterEach(() => {
  vi.unstubAllGlobals()
  route.mockReset()
})

describe('request scope during ERP route resolution', () => {
  it('never dispatches an old-account write after asynchronous route discovery', async () => {
    let resolveRoute!: (path: string) => void
    route.mockImplementationOnce(() => new Promise<string>(resolve => { resolveRoute = resolve }))
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const pending = api.post('/api/orders', { order_number: 'old-account' })
    const rejected = expect(pending).rejects.toBeInstanceOf(AccountSwitchedError)
    productReadAccountEpoch.value++
    resolveRoute('/api/mod/xcagi-erp-domain-bridge/orders')
    await rejected
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('dispatches the resolved route when the initiating account has not changed', async () => {
    route.mockResolvedValueOnce('/api/mod/xcagi-erp-domain-bridge/orders')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ success: true }), {
      headers: { 'content-type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.get('/api/orders')).resolves.toEqual({ success: true })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:5001/api/mod/xcagi-erp-domain-bridge/orders')
  })
})

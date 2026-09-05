import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { payment, refunds, wallet } from './wallet'
import { setAuthTokens } from '../infrastructure/storage/tokenStore'

// Keep the real shared/requestJson path: only the network and clock are replaced.
describe('wallet read request deadlines', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setAuthTokens({ access_token: 'wallet-read-test-token' })
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it.each([
    { path: '/api/wallet/balance', read: () => wallet.balance() },
    { path: '/api/wallet/overview?limit=20&offset=0', read: () => wallet.walletOverview() },
    { path: '/api/wallet/transactions?limit=50&offset=0', read: () => wallet.transactions() },
    { path: '/api/payment/my-plan', read: () => payment.paymentMyPlan() },
    { path: '/api/payment/orders?limit=20&offset=0', read: () => payment.paymentOrders('', 20, 0, { timeoutMs: 10_000 }) },
    { path: '/api/refunds/my', read: () => refunds.refundsMy({ timeoutMs: 10_000 }) },
  ])('aborts $path after ten seconds while retaining authentication', async ({ path, read }) => {
    const mockFetch = vi.fn(
      (_url: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('aborted', 'AbortError'))
          })
        }),
    )
    vi.stubGlobal('fetch', mockFetch)

    const pending = read()
    const assertion = expect(pending).rejects.toMatchObject({ status: 408, message: expect.stringContaining('超时') })
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(mockFetch).toHaveBeenCalledWith(path, expect.objectContaining({ method: 'GET', credentials: 'include' }))
    const request = mockFetch.mock.calls[0]?.[1]
    expect(new Headers(request?.headers).get('Authorization')).toBe('Bearer wallet-read-test-token')
    expect(request?.signal).toBeDefined()
    expect(request).not.toHaveProperty('timeoutMs')

    await vi.advanceTimersByTimeAsync(9_999)
    expect(request?.signal?.aborted).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    await assertion
    expect(request?.signal?.aborted).toBe(true)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('returns a real zero balance and clears its deadline after success', async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ balance: 0 }), { status: 200 }))
    vi.stubGlobal('fetch', mockFetch)

    await expect(wallet.balance()).resolves.toEqual({ balance: 0 })

    expect(vi.getTimerCount()).toBe(0)
    const request = mockFetch.mock.calls[0]?.[1] as RequestInit
    expect(request.signal?.aborted).toBe(false)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(request.signal?.aborted).toBe(false)
  })
})

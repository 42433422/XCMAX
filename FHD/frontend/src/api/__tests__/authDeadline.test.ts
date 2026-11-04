import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { primeCsrfCookie } from '../core'
import { authApi } from '../auth'
import { apiFetch } from '@/utils/apiBase'
import { applyMarketTokensAfterFhdLogin, fetchSessionMarketHandoff, persistMarketTokensFromHandoff, readCurrentMarketAccessToken } from '../marketAccount'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'

const csrf = vi.hoisted(() => ({ value: '' }))
vi.mock('@/utils/csrfCookie', () => ({ readCsrfTokenFromCookie: () => csrf.value, shouldAttachCsrfHeader: () => false }))
vi.mock('@/utils/apiBase', () => ({ getApiBase: () => '', apiFetch: vi.fn() }))
vi.mock('@/utils/erpDomainPaths', () => ({ resolveErpApiPathWhenReady: async (value: string) => value }))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => ({ clear: vi.fn() }) }))
vi.mock('@/utils/platformShellApi', () => ({ clearDeliverableStatusCache: vi.fn() }))

function stalled(options?: RequestInit): Promise<Response> {
  return new Promise((_, reject) => {
    const signal = options?.signal
    const abort = () => reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'))
    if (signal?.aborted) abort()
    else signal?.addEventListener('abort', abort, { once: true })
  })
}
beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); csrf.value = ''; localStorage.clear() })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('bounded authentication operations', () => {
  it('reuses an existing CSRF cookie without a health request', async () => {
    csrf.value = 'test-csrf'
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}'))
    vi.stubGlobal('fetch', fetchMock)
    await primeCsrfCookie()
    expect(fetchMock).not.toHaveBeenCalled()
  })
  it('bounds the whole CSRF probe and aborts the underlying request', async () => {
    const fetchMock = vi.fn((_url, options) => stalled(options))
    vi.stubGlobal('fetch', fetchMock)
    let settled = false
    void primeCsrfCookie({ timeoutMs: 200 }).finally(() => { settled = true }).catch(() => undefined)
    await vi.advanceTimersByTimeAsync(201)
    expect(settled).toBe(true)
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true)
  })
  it('cancels CSRF probes before and during the health request', async () => {
    const fetchMock = vi.fn((_url, options) => stalled(options))
    vi.stubGlobal('fetch', fetchMock)
    const cancelled = new AbortController()
    cancelled.abort()
    await expect(primeCsrfCookie({ signal: cancelled.signal })).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetchMock).not.toHaveBeenCalled()
    const active = new AbortController()
    const pending = primeCsrfCookie({ signal: active.signal })
    active.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  }, 1_000)
  it('caps logout including a slow health probe and clears all credentials even on timeout', async () => {
    localStorage.setItem('xcagi_market_access_token', 'access')
    localStorage.setItem('xcagi_market_refresh_token', 'refresh')
    localStorage.setItem('xcagi_market_user_json', '{}')
    const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
      if (String(url).includes('/health')) {
        await new Promise(resolve => setTimeout(resolve, 2_000))
        csrf.value = 'test-csrf'
        return new Response('{}')
      }
      return stalled(options)
    })
    vi.stubGlobal('fetch', fetchMock)
    let rejected = false
    void authApi.logout().catch(() => { rejected = true })
    await vi.advanceTimersByTimeAsync(10_001)
    expect(rejected).toBe(true)
    expect(localStorage.getItem('xcagi_market_access_token')).toBeNull()
    expect(localStorage.getItem('xcagi_market_refresh_token')).toBeNull()
    expect(localStorage.getItem('xcagi_market_user_json')).toBeNull()
  })
  it('cancels the login retry delay without issuing another request', async () => {
    csrf.value = 'test-csrf'
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 503, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    let settled = false
    void authApi.login('user', 'password', 'enterprise', '', { signal: controller.signal }).catch(() => { settled = true })
    await vi.advanceTimersByTimeAsync(1)
    controller.abort()
    await vi.advanceTimersByTimeAsync(10)
    expect(settled).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('retires a pre-logout handoff through real logout/login A -> B -> A transitions', async () => {
    csrf.value = 'test-csrf'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ success: true }), { headers: { 'Content-Type': 'application/json' } })))
    const account = (id: number) => {
      const profile = { tenantId: 9, marketUserId: id, accountKind: 'enterprise' }
      setRuntimeTenantStorageScopeInput(profile)
      updateProductReadAccountScope(profile)
    }
    account(1)
    await applyMarketTokensAfterFhdLogin({ market_access_token: 'old-a', market_refresh_token: 'old-refresh' })
    let finish!: (response: Response) => void
    vi.mocked(apiFetch).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const stale = fetchSessionMarketHandoff()
    await authApi.logout()
    expect(readCurrentMarketAccessToken()).toBe('')
    await authApi.login('b', 'password')
    account(2)
    await applyMarketTokensAfterFhdLogin({ market_access_token: 'b' })
    expect(readCurrentMarketAccessToken()).toBe('b')
    await authApi.logout()
    await authApi.login('a', 'password')
    account(1)
    await applyMarketTokensAfterFhdLogin({ market_access_token: 'new-a', market_refresh_token: 'new-refresh' })
    finish(new Response(JSON.stringify({ success: true, data: { market_access_token: 'old-a', market_refresh_token: 'old-refresh' } })))
    persistMarketTokensFromHandoff(await stale)
    expect(readCurrentMarketAccessToken()).toBe('new-a')
    expect(localStorage.getItem('xcagi_market_refresh_token')).toBe('new-refresh')
  })
})

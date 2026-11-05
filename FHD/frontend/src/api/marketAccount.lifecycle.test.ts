import { beforeEach, describe, expect, it, vi } from 'vitest'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { apiFetch } from '@/utils/apiBase'
import {
  applyMarketTokensAfterFhdLogin,
  fetchSessionMarketHandoff,
  persistMarketTokensFromHandoff,
  LS_MARKET_ACCESS_TOKEN,
  LS_MARKET_REFRESH_TOKEN,
  readCurrentMarketAccessToken,
} from './marketAccount'

vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn(), getApiBase: () => '' }))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
function response(token: string, refresh = '', status = 200) {
  return new Response(JSON.stringify({ success: status === 200, data: { market_access_token: token, market_refresh_token: refresh } }), { status })
}
beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  setRuntimeTenantStorageScopeInput(null)
  invalidateEnterpriseSessionCache()
})

describe('market credential lifecycle', () => {
  it('only reuses credentials for the current verified user, even within one tenant', () => {
    localStorage.setItem(LS_MARKET_ACCESS_TOKEN, 'unowned-legacy')
    setRuntimeTenantStorageScopeInput({ tenantId: 9, localUserId: 1, accountKind: 'enterprise' })
    expect(readCurrentMarketAccessToken()).toBe('')
    persistMarketTokensFromHandoff({ token: 'a', market_base_url: '' })
    expect(readCurrentMarketAccessToken()).toBe('a')
    setRuntimeTenantStorageScopeInput({ tenantId: 9, localUserId: 2, accountKind: 'enterprise' })
    expect(readCurrentMarketAccessToken()).toBe('')
  })
  it('reads a handoff without committing either credential', async () => {
    vi.mocked(apiFetch).mockResolvedValue(response('a', 'refresh-a'))
    const handoff = await fetchSessionMarketHandoff()
    expect(localStorage.getItem(LS_MARKET_REFRESH_TOKEN)).toBeNull()
    expect(localStorage.getItem(LS_MARKET_ACCESS_TOKEN)).toBeNull()
    persistMarketTokensFromHandoff(handoff)
    expect(localStorage.getItem(LS_MARKET_ACCESS_TOKEN)).toBe('a')
    expect(localStorage.getItem(LS_MARKET_REFRESH_TOKEN)).toBe('refresh-a')
  })

  it.each([200, 401])('ignores an old handoff response (%s) after a new login', async (status) => {
    const pending = deferred<Response>()
    vi.mocked(apiFetch).mockReturnValue(pending.promise)
    const old = applyMarketTokensAfterFhdLogin({})
    invalidateEnterpriseSessionCache()
    await applyMarketTokensAfterFhdLogin({ market_access_token: 'b', market_refresh_token: 'refresh-b' })
    pending.resolve(response('a', 'refresh-a', status))
    await old
    expect(localStorage.getItem(LS_MARKET_ACCESS_TOKEN)).toBe('b')
    expect(localStorage.getItem(LS_MARKET_REFRESH_TOKEN)).toBe('refresh-b')
  })

  it.each([200, 401])('retires an admin handoff (%s) after entering another account', async status => {
    setRuntimeTenantStorageScopeInput({ marketUserId: 1, accountKind: 'admin' })
    persistMarketTokensFromHandoff({ token: 'admin-a', market_base_url: '' })
    const pending = deferred<Response>()
    vi.mocked(apiFetch).mockReturnValue(pending.promise)
    const old = fetchSessionMarketHandoff()
    // /me retains the operator market ID while impersonating_username identifies the target.
    setRuntimeTenantStorageScopeInput({ marketUserId: 1, accountKind: 'admin', marketUsername: 'member-b' })
    productReadAccountEpoch.value++
    expect(readCurrentMarketAccessToken()).toBe('')
    persistMarketTokensFromHandoff({ token: 'member-b', market_base_url: '' })
    pending.resolve(response('admin-a', 'admin-refresh', status))
    persistMarketTokensFromHandoff(await old)
    expect(readCurrentMarketAccessToken()).toBe('member-b')
    expect(localStorage.getItem(LS_MARKET_REFRESH_TOKEN)).toBeNull()
  })

  it('does not commit a cancelled handoff even when its transport resolves late', async () => {
    const pending = deferred<Response>()
    vi.mocked(apiFetch).mockReturnValue(pending.promise)
    const controller = new AbortController()
    const handoff = fetchSessionMarketHandoff({ signal: controller.signal })
    controller.abort()
    pending.resolve(response('cancelled', 'cancelled-refresh'))
    expect(persistMarketTokensFromHandoff(await handoff)).toBe(false)
    expect(localStorage.getItem(LS_MARKET_ACCESS_TOKEN)).toBeNull()
  })

  it('retires A -> B -> A results and results read before logout but committed afterwards', async () => {
    vi.mocked(apiFetch).mockImplementation(async () => response('a', 'refresh-a'))
    const read = await fetchSessionMarketHandoff()
    productReadAccountEpoch.value += 2
    persistMarketTokensFromHandoff(read)
    expect(localStorage.getItem(LS_MARKET_ACCESS_TOKEN)).toBeNull()
    const beforeLogout = await fetchSessionMarketHandoff()
    invalidateEnterpriseSessionCache()
    persistMarketTokensFromHandoff(beforeLogout)
    expect(localStorage.getItem(LS_MARKET_REFRESH_TOKEN)).toBeNull()
  })

  it('does not keep another account refresh credential when a new login has no refresh token', async () => {
    localStorage.setItem(LS_MARKET_REFRESH_TOKEN, 'old-refresh')
    await applyMarketTokensAfterFhdLogin({ market_access_token: 'new-access' })
    expect(localStorage.getItem(LS_MARKET_REFRESH_TOKEN)).toBeNull()
    expect(localStorage.getItem(LS_MARKET_ACCESS_TOKEN)).toBe('new-access')
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, reactive } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { usePrivateDeliverySync } from './usePrivateDeliverySync'

const mocks = vi.hoisted(() => ({ api: vi.fn(), register: vi.fn(), notify: vi.fn() }))
const account = reactive({ loaded: true, marketUserId: 101, tenantId: 1, localUserId: 1,
  impersonatingMarketUserId: null as number | null, impersonatingUsername: '' })
const mods = reactive({ mods: [] as unknown[], modRoutes: [] as unknown[] })
vi.mock('@/composables/useAppToast', () => ({ showAppNotification: (...args: unknown[]) => mocks.notify(...args) }))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => account }))
vi.mock('@/stores/mods', () => ({ useModsStore: () => mods }))
vi.mock('vue-router', () => ({ useRouter: () => ({}) }))
vi.mock('@/utils/apiBase', () => ({ apiFetch: (...args: unknown[]) => mocks.api(...args) }))
vi.mock('@/router/registerModRoutes', () => ({ registerModRoutes: (...args: unknown[]) => mocks.register(...args) }))

const empty = { installed: [], restart_required: [], pending: 0, errors: [] }
function response(data: unknown = empty, ok = true) {
  return { ok, json: async () => ({ success: ok, data }) }
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
let wrapper: VueWrapper | undefined
let sync: ReturnType<typeof usePrivateDeliverySync>
function start() {
  wrapper = mount(defineComponent({ setup() { sync = usePrivateDeliverySync(); return () => null } }))
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout'] })
  Object.assign(account, { loaded: true, marketUserId: 101, tenantId: 1, localUserId: 1,
    impersonatingMarketUserId: null, impersonatingUsername: '' })
  mods.mods = []; mods.modRoutes = []
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
  mocks.api.mockReset().mockImplementation((path: string) => Promise.resolve(response(path === '/api/mod-store/private-delivery/sync' ? empty : [])))
  mocks.notify.mockReset()
  mocks.register.mockReset().mockResolvedValue(undefined)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.useRealTimers(); vi.restoreAllMocks() })

describe('automatic private delivery lifecycle', () => {
  it.each(['anonymous', 'hydrating', 'noWorkspace'])('%s does not call installation', async (kind) => {
    if (kind === 'anonymous') account.marketUserId = 0
    if (kind === 'hydrating') account.loaded = false
    if (kind === 'noWorkspace') { account.tenantId = 0; account.localUserId = 0 }
    start(); await flushPromises(); await vi.advanceTimersByTimeAsync(120_000)
    expect(mocks.api).not.toHaveBeenCalled()
  })

  it('syncs immediately and every 60 seconds with bounded request time', async () => {
    start(); await flushPromises()
    expect(mocks.api).toHaveBeenCalledTimes(1)
    expect(mocks.api).toHaveBeenCalledWith('/api/mod-store/private-delivery/sync', expect.objectContaining({
      method: 'POST', body: '{}', timeoutMs: 45_000, signal: expect.any(AbortSignal),
    }))
    await vi.advanceTimersByTimeAsync(59_999)
    expect(mocks.api).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(mocks.api).toHaveBeenCalledTimes(2)
    expect(sync.result.value).toEqual(empty)
  })

  it('does not overlap an in-flight request and retries a network error', async () => {
    const outstanding = deferred<ReturnType<typeof response>>()
    mocks.api.mockReturnValueOnce(outstanding.promise)
    start(); await flushPromises(); await vi.advanceTimersByTimeAsync(60_000)
    expect(mocks.api).toHaveBeenCalledTimes(1)
    outstanding.resolve(response()); await flushPromises()
    mocks.api.mockRejectedValueOnce(new Error('network unavailable'))
    await vi.advanceTimersByTimeAsync(60_000)
    expect(sync.pending.value).toBe(false)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(mocks.api).toHaveBeenCalledTimes(5)
    expect(sync.result.value).toEqual(empty)
  })

  it('aborts disconnected work and syncs immediately when connection returns', async () => {
    const outstanding = deferred<ReturnType<typeof response>>()
    mocks.api.mockReturnValueOnce(outstanding.promise)
    start(); await flushPromises()
    const signal = mocks.api.mock.calls[0][1].signal as AbortSignal
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    window.dispatchEvent(new Event('offline')); await flushPromises()
    expect(signal.aborted).toBe(true)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(mocks.api).toHaveBeenCalledTimes(1)
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
    window.dispatchEvent(new Event('online')); await flushPromises()
    expect(mocks.api).toHaveBeenCalledTimes(4)
    outstanding.resolve(response({ ...empty, pending: 99 })); await flushPromises()
    expect(sync.result.value?.pending).toBe(0)
  })

  it.each(['marketUserId', 'tenantId', 'localUserId'] as const)(
    '%s change immediately aborts old account and rejects its late response', async (field) => {
      const old = deferred<ReturnType<typeof response>>()
      mocks.api.mockReturnValueOnce(old.promise)
      start(); await flushPromises()
      const signal = mocks.api.mock.calls[0][1].signal as AbortSignal
      account[field] = 202
      expect(signal.aborted).toBe(true)
      expect(sync.result.value).toBeNull()
      old.resolve(response({ ...empty, installed: ['old-account'] }))
      await flushPromises()
      expect(mocks.api).toHaveBeenCalledTimes(2)
      expect(mods.mods).toEqual([])
      expect(mocks.register).not.toHaveBeenCalled()
      expect(sync.result.value?.installed).toEqual([])
    })

  it('stops during impersonation and resumes only after leaving the customer account', async () => {
    const old = deferred<ReturnType<typeof response>>()
    mocks.api.mockReturnValueOnce(old.promise)
    start(); await flushPromises()
    const signal = mocks.api.mock.calls[0][1].signal as AbortSignal
    account.impersonatingMarketUserId = 202
    account.impersonatingUsername = 'customer'
    expect(signal.aborted).toBe(true)
    expect(sync.result.value).toBeNull()
    await flushPromises(); await vi.advanceTimersByTimeAsync(120_000)
    window.dispatchEvent(new Event('online')); await flushPromises()
    expect(mocks.api).toHaveBeenCalledTimes(1)
    Object.assign(account, { impersonatingMarketUserId: null, impersonatingUsername: '' })
    await flushPromises()
    expect(mocks.api).toHaveBeenCalledTimes(2)
    old.resolve(response({ ...empty, installed: ['admin-private'] })); await flushPromises()
    expect(mocks.register).not.toHaveBeenCalled()
  })

  it('coalesces synchronous hydration fields into one current-account request', async () => {
    account.loaded = false; start(); await flushPromises()
    Object.assign(account, { loaded: true, marketUserId: 202, tenantId: 2, localUserId: 2 })
    await flushPromises()
    expect(mocks.api).toHaveBeenCalledTimes(1)
  })

  it('refreshes installed modules and routes after confirmed installation', async () => {
    const runtime = { mod_id: 'private-new', runtime: { sdk_version: 1 } }
    mocks.api.mockResolvedValueOnce(response({ ...empty, installed: ['private-new'] }))
      .mockResolvedValueOnce(response([{ id: 'private-new' }]))
      .mockResolvedValueOnce(response([runtime, { mod_id: 'built-in' }]))
    start(); await flushPromises()
    expect(mods.mods).toEqual([{ id: 'private-new' }])
    expect(mods.modRoutes).toEqual([runtime, { mod_id: 'built-in' }])
    expect(mocks.register).toHaveBeenCalledWith(expect.anything(), [runtime])
  })

  it('cannot publish a delayed module listing after account switch', async () => {
    const listing = deferred<ReturnType<typeof response>>()
    mocks.api.mockResolvedValueOnce(response({ ...empty, installed: ['private-old'] }))
      .mockReturnValueOnce(listing.promise)
      .mockResolvedValueOnce(response([{ mod_id: 'private-old', runtime: {} }]))
    start(); await flushPromises()
    account.marketUserId = 202; await flushPromises()
    listing.resolve(response([{ id: 'private-old' }])); await flushPromises()
    expect(mods.mods).toEqual([])
    expect(mocks.register).not.toHaveBeenCalled()
  })

  it('refreshes menus when rights arrive after an earlier successful installation', async () => {
    mocks.api.mockResolvedValueOnce(response({ ...empty, routes_changed: true }))
    start(); await flushPromises()
    expect(mocks.api).toHaveBeenCalledWith('/api/mods/routes', expect.anything())
    expect(mocks.register).toHaveBeenCalledOnce()
  })

  it('retries failed menu reads on the next cycle without reinstalling', async () => {
    mocks.api.mockResolvedValueOnce(response({ ...empty, installed: ['private-new'] }))
      .mockRejectedValueOnce(new Error('listing offline'))
    start(); await flushPromises()
    expect(mocks.register).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(mocks.register).toHaveBeenCalledOnce()
    expect(mocks.api.mock.calls.filter(([path]) => path === '/api/mod-store/private-delivery/sync')).toHaveLength(2)
  })

  it('notifies about restart once until the pending update or account changes', async () => {
    mocks.api.mockResolvedValue(response({ ...empty, restart_required: ['private-new'] }))
    start(); await flushPromises(); await vi.advanceTimersByTimeAsync(120_000)
    expect(mocks.notify).toHaveBeenCalledExactlyOnceWith('私有扩展更新已就绪', '下次重启后生效')
    account.marketUserId = 202; await flushPromises()
    expect(mocks.notify).toHaveBeenCalledTimes(2)
  })

  it('logout and unmount clear state, listeners, timers and requests', async () => {
    start(); await flushPromises()
    account.marketUserId = 0
    expect(sync.result.value).toBeNull()
    await vi.advanceTimersByTimeAsync(120_000)
    expect(mocks.api).toHaveBeenCalledTimes(1)
    account.marketUserId = 101; await flushPromises()
    wrapper?.unmount(); wrapper = undefined
    window.dispatchEvent(new Event('online')); await vi.advanceTimersByTimeAsync(120_000)
    expect(mocks.api).toHaveBeenCalledTimes(2)
    expect(vi.getTimerCount()).toBe(0)
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, disposePinia, setActivePinia, type Pinia } from 'pinia'
import { nextTick } from 'vue'
import { PLATFORM_MODEL_CHANGED_EVENT, PLATFORM_MODEL_CHANGED_KEY } from '@/api/platformModel'
import { useAccountRuntimeStore } from './accountRuntime'

const boundary = await vi.hoisted(async () => {
  const { reactive, ref } = await import('vue')
  return {
    get: vi.fn(), post: vi.fn(), authEpoch: ref(0), accountEpoch: ref(0),
    account: reactive({ workspaceReady: true, workspaceHydrationReady: true, localUserId: 41 as number | null, isImpersonating: false }),
  }
})
vi.mock('@/api/core', () => ({ api: { get: boundary.get, post: boundary.post } }))
vi.mock('./accountProfile', () => ({ useAccountProfileStore: () => boundary.account }))
vi.mock('@/utils/productReadAccountScope', () => ({ productReadAccountEpoch: boundary.accountEpoch }))
vi.mock('@/utils/authSessionCache', () => ({
  getAuthSessionEpoch: () => boundary.authEpoch.value,
  captureAuthSession: () => {
    const auth = boundary.authEpoch.value, owner = boundary.accountEpoch.value
    return () => auth === boundary.authEpoch.value && owner === boundary.accountEpoch.value
  },
}))

const endpoint = '/api/desktop/agent-runtime/qualification'
const snapshot = (qualification = 'passed', model = 'account-model') => ({
  success: true, managed_by: 'account', qualification,
  route: { model, route_identity: `route-${model}` },
})
function deferred<T = unknown>() {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
async function settle() { for (let i = 0; i < 12; i++) { await Promise.resolve(); await nextTick() } }
let pinia: Pinia
beforeEach(() => {
  vi.useFakeTimers()
  boundary.get.mockReset().mockResolvedValue(snapshot())
  boundary.post.mockReset().mockResolvedValue({ success: true, qualification: 'passed' })
  boundary.authEpoch.value = boundary.accountEpoch.value = 0
  Object.assign(boundary.account, { workspaceReady: true, workspaceHydrationReady: true, localUserId: 41, isImpersonating: false })
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => { disposePinia(pinia); vi.useRealTimers(); vi.restoreAllMocks() })

describe('account runtime lifecycle', () => {
  it('checks a required route only on an explicit action and reads back its persisted qualification', async () => {
    boundary.get.mockResolvedValue(snapshot('required'))
    boundary.post.mockImplementation(async () => { boundary.get.mockResolvedValue(snapshot()); return { success: true } })
    const persistedFlag = vi.spyOn(Storage.prototype, 'setItem')
    const runtime = useAccountRuntimeStore()
    await runtime.start()
    expect(runtime.status?.qualification).toBe('required')
    expect(boundary.post).not.toHaveBeenCalled()
    await runtime.retry()
    expect(boundary.post).toHaveBeenCalledExactlyOnceWith(endpoint, { retry: true }, expect.objectContaining({ timeoutMs: 600_000, retry: false, signal: expect.any(AbortSignal) }))
    expect(boundary.get).toHaveBeenCalledTimes(3)
    expect(boundary.get).toHaveBeenCalledWith(endpoint, {}, expect.objectContaining({ cache: 'no-store', retry: false }))
    expect(runtime.status?.qualification).toBe('passed')
    expect(runtime.message).toContain('account-model')
    expect(runtime.busy).toBe(false)
    expect(persistedFlag).not.toHaveBeenCalled()
  })

  it('reads a valid receipt after restart without starting another model call', async () => {
    const runtime = useAccountRuntimeStore()
    await runtime.start()
    runtime.stop()
    expect(runtime.status).toBeNull()
    await runtime.start()
    expect(boundary.get).toHaveBeenCalledTimes(2)
    expect(boundary.post).not.toHaveBeenCalled()
    expect(runtime.message).toContain('运行验收已通过')
  })

  it('coalesces settings and startup even when the read-only settings request starts first', async () => {
    const first = deferred()
    boundary.get.mockReturnValueOnce(first.promise)
    const runtime = useAccountRuntimeStore()
    const settings = runtime.refresh(), startup = runtime.start(), again = runtime.refresh()
    expect(boundary.get).toHaveBeenCalledOnce()
    first.resolve(snapshot('required'))
    await Promise.all([settings, startup, again])
    expect(boundary.post).not.toHaveBeenCalled()
    expect(boundary.get).toHaveBeenCalledOnce()
    expect(runtime.status?.qualification).toBe('required')
  })

  it('coalesces an explicit check with an in-flight status read without replaying the attempt', async () => {
    const first = deferred()
    boundary.get.mockReturnValueOnce(first.promise)
    const runtime = useAccountRuntimeStore()
    const startup = runtime.start(), click = runtime.retry(), repeatedClick = runtime.retry()
    expect(boundary.post).not.toHaveBeenCalled()
    first.resolve(snapshot('required'))
    await Promise.all([startup, click, repeatedClick])
    expect(boundary.post).toHaveBeenCalledExactlyOnceWith(endpoint, { retry: true }, expect.objectContaining({ retry: false }))
    expect(runtime.status?.qualification).toBe('passed')
  })

  it.each(['same-tab', 'other-tab', 'account', 'auth'])('only refreshes missing qualification after an automatic %s change', async cause => {
    boundary.get.mockResolvedValue(snapshot('required'))
    const runtime = useAccountRuntimeStore()
    await runtime.start()
    boundary.get.mockClear()
    if (cause === 'same-tab') window.dispatchEvent(new Event(PLATFORM_MODEL_CHANGED_EVENT))
    else if (cause === 'other-tab') window.dispatchEvent(new StorageEvent('storage', { key: PLATFORM_MODEL_CHANGED_KEY, newValue: 'changed' }))
    else if (cause === 'account') { boundary.accountEpoch.value++; boundary.account.localUserId = 42 }
    else boundary.authEpoch.value++
    await settle()
    expect(boundary.get).toHaveBeenCalled()
    expect(runtime.status?.qualification).toBe('required')
    expect(boundary.post).not.toHaveBeenCalled()
  })

  it.each(['failed', 'interrupted'])('requires an explicit retry for a previous %s attempt', async qualification => {
    boundary.get.mockResolvedValue(snapshot(qualification))
    const runtime = useAccountRuntimeStore()
    await runtime.start(); await runtime.start()
    expect(runtime.failed).toBe(true)
    expect(boundary.post).not.toHaveBeenCalled()
    boundary.post.mockImplementation(async () => { boundary.get.mockResolvedValue(snapshot()); return { success: true } })
    await runtime.retry()
    expect(boundary.post).toHaveBeenCalledExactlyOnceWith(endpoint, { retry: true }, expect.objectContaining({ retry: false }))
    expect(runtime.status?.qualification).toBe('passed')
  })

  it('only polls a server-owned in-progress qualification, including an explicit refresh', async () => {
    boundary.get.mockResolvedValue(snapshot('in_progress'))
    const runtime = useAccountRuntimeStore()
    await runtime.start()
    expect(runtime.busy).toBe(true)
    await runtime.retry()
    expect(boundary.post).not.toHaveBeenCalled()
    boundary.get.mockResolvedValue(snapshot())
    await vi.advanceTimersByTimeAsync(5_000)
    expect(boundary.get).toHaveBeenCalledTimes(3)
    expect(runtime.status?.qualification).toBe('passed')
    expect(boundary.post).not.toHaveBeenCalled()
  })

  it('reads back a lost POST response and polls the original attempt without posting again', async () => {
    boundary.get.mockResolvedValueOnce(snapshot('required')).mockResolvedValueOnce(snapshot('required')).mockResolvedValue(snapshot('in_progress'))
    boundary.post.mockRejectedValue({ status: 0, message: 'transport acknowledgement lost' })
    const runtime = useAccountRuntimeStore()
    await runtime.start()
    await runtime.retry()
    expect(runtime.status?.qualification).toBe('in_progress')
    expect(runtime.failed).toBe(false)
    boundary.get.mockResolvedValue(snapshot())
    await vi.advanceTimersByTimeAsync(5_000)
    expect(runtime.status?.qualification).toBe('passed')
    expect(boundary.post).toHaveBeenCalledOnce()
  })

  it('does not call a success response ready when persisted qualification is still missing', async () => {
    boundary.get.mockResolvedValue(snapshot('required'))
    const runtime = useAccountRuntimeStore()
    await runtime.start()
    await runtime.retry()
    expect(runtime.status?.qualification).toBe('required')
    expect(runtime.message).not.toContain('运行验收已通过')
    expect(boundary.post).toHaveBeenCalledOnce()
  })

  it.each(['same-tab', 'other-tab'])('retires a stale POST after a %s model change', async source => {
    const old = deferred()
    boundary.get.mockResolvedValueOnce(snapshot('required', 'old-model')).mockResolvedValueOnce(snapshot('required', 'old-model')).mockResolvedValue(snapshot('passed', 'new-model'))
    boundary.post.mockReturnValueOnce(old.promise)
    const runtime = useAccountRuntimeStore()
    await runtime.start()
    const first = runtime.retry()
    await settle()
    const signal = boundary.post.mock.calls[0][2].signal as AbortSignal
    if (source === 'same-tab') window.dispatchEvent(new Event(PLATFORM_MODEL_CHANGED_EVENT))
    else window.dispatchEvent(new StorageEvent('storage', { key: PLATFORM_MODEL_CHANGED_KEY, newValue: 'changed' }))
    expect(signal.aborted).toBe(true)
    await settle()
    expect(runtime.message).toContain('new-model')
    old.resolve({ success: true, qualification: 'passed', route: { model: 'old-model' } })
    await first
    expect(runtime.message).toContain('new-model')
    expect(runtime.message).not.toContain('old-model')
    expect(boundary.get).toHaveBeenCalledTimes(3)
  })

  it.each(['account', 'auth', 'impersonation'])('immediately retires a late result after %s changes', async cause => {
    const old = deferred()
    boundary.get.mockReturnValueOnce(old.promise)
    const runtime = useAccountRuntimeStore()
    const first = runtime.start()
    const signal = boundary.get.mock.calls[0][2].signal as AbortSignal
    boundary.account.workspaceReady = false
    if (cause === 'account') { boundary.accountEpoch.value++; boundary.account.localUserId = 42 }
    else if (cause === 'auth') boundary.authEpoch.value++
    else boundary.account.isImpersonating = true
    expect(signal.aborted).toBe(true)
    expect(runtime.status).toBeNull()
    old.resolve(snapshot('passed', 'old-account'))
    await first
    expect(runtime.message).not.toContain('old-account')
    expect(boundary.post).not.toHaveBeenCalled()
    if (cause !== 'impersonation') {
      boundary.account.workspaceReady = true
      await settle()
      expect(runtime.status?.qualification).toBe('passed')
    }
  })

  it('waits for an authenticated hydrated account and never probes an impersonated account', async () => {
    boundary.get.mockResolvedValue(snapshot('required'))
    boundary.account.localUserId = null
    const runtime = useAccountRuntimeStore()
    await runtime.start()
    expect(boundary.get).not.toHaveBeenCalled()
    boundary.account.isImpersonating = true
    boundary.account.localUserId = 41
    await runtime.start()
    expect(boundary.get).not.toHaveBeenCalled()
    boundary.account.workspaceHydrationReady = false
    boundary.account.isImpersonating = false
    await runtime.start()
    expect(boundary.get).not.toHaveBeenCalled()
    boundary.account.workspaceHydrationReady = true
    await settle()
    expect(boundary.get).toHaveBeenCalledOnce()
    expect(runtime.status?.qualification).toBe('required')
    expect(boundary.post).not.toHaveBeenCalled()
  })

  it('keeps deployment-owned configuration read-only on startup and on a user check', async () => {
    boundary.get.mockResolvedValue({ ...snapshot('required'), managed_by: 'deployment', message: '请由部署方完成本机验收' })
    const runtime = useAccountRuntimeStore()
    await runtime.start(); await runtime.retry()
    expect(boundary.post).not.toHaveBeenCalled()
    expect(runtime.message).toBe('请由部署方完成本机验收')
  })

  it('shows a structured blocked reason without calling the model', async () => {
    boundary.get.mockRejectedValue({ status: 409, data: { ...snapshot('blocked'), success: false, error_code: 'runtime_configuration_required', message: '请补全模型容量' } })
    const runtime = useAccountRuntimeStore()
    await runtime.start()
    expect(runtime.failed).toBe(true)
    expect(runtime.message).toBe('请补全模型容量')
    expect(boundary.post).not.toHaveBeenCalled()
  })

  it.each([{ ...snapshot(), route: undefined }, { status: 'ready' }])('rejects malformed success payloads', async result => {
    boundary.get.mockResolvedValue(result)
    const runtime = useAccountRuntimeStore()
    await runtime.start()
    expect(runtime.status).toBeNull()
    expect(runtime.failed).toBe(true)
    expect(runtime.message).not.toContain('运行验收已通过')
    expect(boundary.post).not.toHaveBeenCalled()
  })

  it('retires polling on logout and ignores model events after shutdown', async () => {
    boundary.get.mockResolvedValue(snapshot('in_progress'))
    const runtime = useAccountRuntimeStore()
    await runtime.start()
    runtime.stop()
    window.dispatchEvent(new Event(PLATFORM_MODEL_CHANGED_EVENT))
    await vi.advanceTimersByTimeAsync(10_000)
    expect(boundary.get).toHaveBeenCalledOnce()
    expect(runtime.status).toBeNull()
    expect(runtime.busy).toBe(false)
    expect(boundary.post).not.toHaveBeenCalled()
  })
})

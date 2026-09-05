import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { api } from '../api'
import type { LlmCatalogResponse } from '../api/llm'
import { requestJson } from '../infrastructure/http/client'
import { useWalletLlm, type WalletLlmApi } from './useWalletLlm'
import { confirmDanger } from './useDangerConfirm'
import { useAuthStore } from '../stores/auth'

vi.mock('../api', () => ({
  api: {
    llmStatus: vi.fn(),
    llmCatalog: vi.fn(),
    llmSavePreferences: vi.fn(),
    llmSaveCredentials: vi.fn(),
    llmDeleteCredentials: vi.fn(),
  },
}))

vi.mock('../stores/auth', async () => {
  const { reactive } = await import('vue')
  const auth = reactive({ user: { id: 1 } })
  return { useAuthStore: () => auth }
})

vi.mock('../infrastructure/http/client', () => ({ requestJson: vi.fn() }))
vi.mock('./useDangerConfirm', () => ({ confirmDanger: vi.fn() }))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function catalogResponse(model = 'test-model-original'): LlmCatalogResponse {
  return {
    providers: [{ provider: 'openai', label: 'OpenAI', models: [model] }],
    preferences: { provider: 'openai', model },
    fernet_configured: true,
  }
}

const confirmedStatus = [{ provider: 'openai', has_user_override: true, has_platform_key: false }]

describe('useWalletLlm read recovery', () => {
  const wrappers: VueWrapper[] = []

  function mountReader() {
    let state!: WalletLlmApi
    const wrapper = mount(defineComponent({
      setup() {
        state = useWalletLlm()
        return () => h('div')
      },
    }))
    wrappers.push(wrapper)
    return { state, wrapper }
  }

  function expectNoWrites() {
    expect(api.llmSavePreferences).not.toHaveBeenCalled()
    expect(api.llmSaveCredentials).not.toHaveBeenCalled()
    expect(api.llmDeleteCredentials).not.toHaveBeenCalled()
    expect(requestJson).not.toHaveBeenCalled()
    expect(confirmDanger).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
  }

  beforeEach(() => {
    vi.useFakeTimers()
    vi.resetAllMocks()
    const auth = useAuthStore()
    auth.user = { id: 1 } as typeof auth.user
    localStorage.setItem('modstore_token', 'wallet-model-read-test-token')
    vi.mocked(api.llmCatalog).mockResolvedValue(catalogResponse())
    vi.mocked(api.llmStatus).mockResolvedValue({ providers: confirmedStatus })
    vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Unexpected real network request') }))
  })

  afterEach(() => {
    for (const wrapper of wrappers.splice(0)) wrapper.unmount()
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('stops loading after the first catalog failure and recovers through manual refresh', async () => {
    const initialRead = deferred<LlmCatalogResponse>()
    vi.mocked(api.llmCatalog).mockReturnValueOnce(initialRead.promise)
    const { state } = mountReader()
    expect(state.llmCatalogLoading.value).toBe(true)
    expect(state.catalog.value).toBeNull()

    initialRead.reject(new Error('request aborted after deadline'))
    await flushPromises()

    expect(state.llmCatalogLoading.value).toBe(false)
    expect(state.catalog.value).toBeNull()
    expect(state.llmErr.value).toBe('模型目录加载失败，请刷新模型列表重试。')
    expect(state.llmErr.value).not.toContain('request aborted')
    expect(api.llmCatalog).toHaveBeenNthCalledWith(1, false, { timeoutMs: 20_000 })
    expect(api.llmStatus).toHaveBeenNthCalledWith(1, { timeoutMs: 20_000 })

    const retryRead = deferred<LlmCatalogResponse>()
    vi.mocked(api.llmCatalog).mockReturnValueOnce(retryRead.promise)
    const retry = state.refreshCatalog(true)
    expect(state.llmCatalogLoading.value).toBe(true)
    expect(state.llmErr.value).toBe('')
    retryRead.resolve(catalogResponse('test-model-recovered'))
    await retry
    await flushPromises()

    expect(state.catalog.value).toEqual(catalogResponse('test-model-recovered'))
    expect(state.llmStatusList.value).toEqual(confirmedStatus)
    expect(state.llmCatalogLoading.value).toBe(false)
    expect(state.llmErr.value).toBe('')
    expect(api.llmCatalog).toHaveBeenNthCalledWith(2, true, { timeoutMs: 20_000 })
    expect(api.llmStatus).toHaveBeenNthCalledWith(2, { timeoutMs: 20_000 })
    expectNoWrites()
  })

  it('keeps an initially failed status unknown and restores it on manual refresh', async () => {
    vi.mocked(api.llmStatus).mockRejectedValueOnce(new Error('status unavailable'))
    const { state } = mountReader()
    await flushPromises()

    expect(state.llmStatusList.value).toEqual([])
    expect(state.catalog.value).toEqual(catalogResponse())
    expect(state.llmCatalogLoading.value).toBe(false)
    expect(state.llmErr.value).toBe('模型服务状态加载失败，请刷新模型列表重试。')

    await state.refreshCatalog(true)
    await flushPromises()

    expect(state.llmStatusList.value).toEqual(confirmedStatus)
    expect(state.llmCatalogLoading.value).toBe(false)
    expect(state.llmErr.value).toBe('')
    expect(api.llmStatus).toHaveBeenCalledTimes(2)
    expect(api.llmStatus).toHaveBeenLastCalledWith({ timeoutMs: 20_000 })
    expectNoWrites()
  })

  it('retains the confirmed catalog and selection when a later catalog read fails', async () => {
    const { state } = mountReader()
    await flushPromises()
    const previousCatalog = state.catalog.value
    const previousStatus = state.llmStatusList.value
    const laterRead = deferred<LlmCatalogResponse>()
    vi.mocked(api.llmCatalog).mockReturnValueOnce(laterRead.promise)

    const refresh = state.loadCatalog(true)
    expect(state.llmCatalogLoading.value).toBe(true)
    expect(state.catalog.value).toBe(previousCatalog)
    laterRead.reject(new Error('upstream timed out'))
    await refresh

    expect(state.catalog.value).toBe(previousCatalog)
    expect(state.llmStatusList.value).toBe(previousStatus)
    expect(state.selectedProvider.value).toBe('openai')
    expect(state.selectedModel.value).toBe('test-model-original')
    expect(state.llmCatalogLoading.value).toBe(false)
    expect(state.llmErr.value).toBe('模型目录加载失败，当前显示上次加载的目录；请刷新模型列表重试。')
    expect(api.llmCatalog).toHaveBeenLastCalledWith(true, { timeoutMs: 20_000 })
    expect(api.llmStatus).toHaveBeenCalledTimes(1)
    expectNoWrites()
  })

  it('retains confirmed provider status when a later status read fails', async () => {
    const { state } = mountReader()
    await flushPromises()
    const previousStatus = state.llmStatusList.value
    const previousCatalog = state.catalog.value
    vi.mocked(api.llmStatus).mockRejectedValueOnce(new Error('service timeout'))

    await state.loadLlmStatus()

    expect(state.llmStatusList.value).toBe(previousStatus)
    expect(state.llmStatusList.value).toEqual(confirmedStatus)
    expect(state.catalog.value).toBe(previousCatalog)
    expect(state.llmCatalogLoading.value).toBe(false)
    expect(state.llmErr.value).toBe('模型服务状态加载失败，请刷新模型列表重试。')
    expect(api.llmStatus).toHaveBeenLastCalledWith({ timeoutMs: 20_000 })
    expect(api.llmCatalog).toHaveBeenCalledTimes(1)
    expectNoWrites()
  })

  it('removes periodic and visibility refreshes on unmount without writing preferences', async () => {
    const { wrapper } = mountReader()
    await flushPromises()
    expect(api.llmCatalog).toHaveBeenCalledTimes(1)
    expect(api.llmStatus).toHaveBeenCalledTimes(1)

    wrapper.unmount()
    wrappers.splice(wrappers.indexOf(wrapper), 1)
    expect(vi.getTimerCount()).toBe(0)
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(8 * 60 * 1_000)

    expect(api.llmCatalog).toHaveBeenCalledTimes(1)
    expect(api.llmStatus).toHaveBeenCalledTimes(1)
    expectNoWrites()
  })

  it('clears account-specific model data before a different account read fails', async () => {
    const { state } = mountReader()
    await flushPromises()
    state.byokKey.openai = 'unsaved-old-account-key'
    vi.mocked(api.llmCatalog).mockRejectedValue(new Error('offline'))
    vi.mocked(api.llmStatus).mockRejectedValue(new Error('offline'))
    const auth = useAuthStore()
    auth.user = { id: 2 } as typeof auth.user
    expect(state.catalog.value).toBeNull()
    expect(state.llmStatusList.value).toEqual([])
    expect(state.selectedProvider.value).toBe('')
    expect(state.byokKey.openai).toBeUndefined()
    await flushPromises()
    expect(state.catalog.value).toBeNull()
    expect(state.llmCatalogLoading.value).toBe(false)
    expectNoWrites()
  })

  it('does not let a delayed old-account catalog or status overwrite the new account', async () => {
    const oldCatalog = deferred<LlmCatalogResponse>()
    const oldStatus = deferred<{ providers: typeof confirmedStatus }>()
    vi.mocked(api.llmCatalog).mockReturnValueOnce(oldCatalog.promise)
    vi.mocked(api.llmStatus).mockReturnValueOnce(oldStatus.promise)
    const { state } = mountReader()
    vi.mocked(api.llmCatalog).mockResolvedValue(catalogResponse('new-account-model'))
    vi.mocked(api.llmStatus).mockResolvedValue({ providers: [] })
    const auth = useAuthStore()
    auth.user = { id: 2 } as typeof auth.user
    await flushPromises()
    expect(state.selectedModel.value).toBe('new-account-model')
    oldCatalog.resolve(catalogResponse('old-account-model'))
    oldStatus.resolve({ providers: confirmedStatus })
    await flushPromises()
    expect(state.selectedModel.value).toBe('new-account-model')
    expect(state.llmStatusList.value).toEqual([])
    expectNoWrites()
  })
})

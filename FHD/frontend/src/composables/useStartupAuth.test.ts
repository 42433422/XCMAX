import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useStartupAuth } from '@/composables/useStartupAuth'
import { flushPromises } from '@vue/test-utils'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { fetchSessionMarketHandoff, persistMarketTokensFromHandoff } from '@/api/marketAccount'
import { STARTUP_READY_TIMEOUT_MS, useStartupSplash } from '@/composables/useStartupSplash'

vi.mock('@/api/auth', () => ({
  authApi: {
    validateSession: vi.fn(),
  },
}))

vi.mock('@/api/marketAccount', () => ({
  fetchSessionMarketHandoff: vi.fn().mockResolvedValue({}),
  persistMarketTokensFromHandoff: vi.fn(),
}))

vi.mock('@/utils/productSku', () => ({
  fetchProductSku: vi.fn().mockResolvedValue('generic'),
  isEnterpriseEdition: vi.fn().mockReturnValue(false),
}))

vi.mock('@/stores/mods', () => ({
  readEntitledModIdsFromAuthPayload: vi.fn().mockReturnValue([]),
  useModsStore: vi.fn(),
}))

vi.mock('@/utils/startupRedirect', () => ({
  buildLoginLocation: vi.fn().mockReturnValue({ name: 'login' }),
}))

vi.mock('@/utils/hostPackOnboardingGate', () => ({
  clearHostPackSkippedSession: vi.fn(),
}))

import { authApi } from '@/api/auth'

describe('useStartupAuth', () => {
  let mockRouter: any
  let mockModsStore: any
  let mockDismiss: any

  beforeEach(() => {
    setActivePinia(createPinia())
    mockRouter = { replace: vi.fn() }
    mockModsStore = { initialize: vi.fn().mockResolvedValue(undefined) }
    mockDismiss = vi.fn()
    vi.clearAllMocks()
    vi.mocked(fetchSessionMarketHandoff).mockResolvedValue(null)
  })
  afterEach(() => { vi.useRealTimers() })

  function getComposable() {
    return useStartupAuth({
      router: mockRouter,
      modsStore: mockModsStore,
      dismissStartupSplashImmediate: mockDismiss,
    })
  }

  it('ensureStartupAuthenticated returns ok on valid session', async () => {
    ;(authApi.validateSession as any).mockResolvedValue({
      success: true,
      data: { valid: true, username: 'testuser' },
    })
    const { ensureStartupAuthenticated } = getComposable()
    const result = await ensureStartupAuthenticated()
    expect(result.ok).toBe(true)
    expect(result.entitledModIds).toEqual([])
  })

  it('ensureStartupAuthenticated redirects on invalid session', async () => {
    ;(authApi.validateSession as any).mockResolvedValue({
      success: false,
    })
    const { ensureStartupAuthenticated } = getComposable()
    const result = await ensureStartupAuthenticated()
    expect(result.ok).toBe(false)
    expect(mockDismiss).toHaveBeenCalled()
    expect(mockRouter.replace).toHaveBeenCalled()
  })

  it('ensureStartupAuthenticated does not send a transient failure to login', async () => {
    ;(authApi.validateSession as any).mockRejectedValue(new Error('Network error'))
    const { ensureStartupAuthenticated } = getComposable()
    const result = await ensureStartupAuthenticated()
    expect(result.ok).toBe(false)
    expect(result.unavailable).toBe(true)
    expect(mockDismiss).not.toHaveBeenCalled()
    expect(mockRouter.replace).not.toHaveBeenCalled()
  })

  it('ensureStartupAuthenticated redirects when the server rejects the session', async () => {
    ;(authApi.validateSession as any).mockRejectedValue(Object.assign(new Error('unauthorized'), { status: 401 }))
    const { ensureStartupAuthenticated } = getComposable()
    const result = await ensureStartupAuthenticated()
    expect(result.ok).toBe(false)
    expect(mockRouter.replace).toHaveBeenCalled()
  })

  it('ensureStartupAuthenticated accepts res.valid === true', async () => {
    ;(authApi.validateSession as any).mockResolvedValue({
      valid: true,
    })
    const { ensureStartupAuthenticated } = getComposable()
    const result = await ensureStartupAuthenticated()
    expect(result.ok).toBe(true)
  })

  it('ensureStartupAuthenticated accepts res.data.valid === true', async () => {
    ;(authApi.validateSession as any).mockResolvedValue({
      data: { valid: true },
    })
    const { ensureStartupAuthenticated } = getComposable()
    const result = await ensureStartupAuthenticated()
    expect(result.ok).toBe(true)
  })

  it('honors explicit invalid session even when the envelope says success', async () => {
    vi.mocked(authApi.validateSession).mockResolvedValue({ success: true, data: { valid: false } })
    await expect(getComposable().ensureStartupAuthenticated()).resolves.toMatchObject({ ok: false })
    expect(mockRouter.replace).toHaveBeenCalledOnce()
    expect(fetchSessionMarketHandoff).not.toHaveBeenCalled()
  })

  it('runEnterpriseStartupAuth returns true for public routes', async () => {
    const { runEnterpriseStartupAuth } = getComposable()
    const result = await runEnterpriseStartupAuth(() => true)
    expect(result).toBe(true)
  })

  it('runEnterpriseStartupAuth returns false when auth fails', async () => {
    ;(authApi.validateSession as any).mockResolvedValue({ success: false })
    const { runEnterpriseStartupAuth } = getComposable()
    const result = await runEnterpriseStartupAuth(() => false)
    expect(result).toBe(false)
  })

  it('runEnterpriseStartupAuth returns true when auth succeeds for non-enterprise', async () => {
    ;(authApi.validateSession as any).mockResolvedValue({
      success: true,
      data: { valid: true, username: 'testuser' },
    })
    const { runEnterpriseStartupAuth } = getComposable()
    const result = await runEnterpriseStartupAuth(() => false)
    expect(result).toBe(true)
  })

  it('syncMarketTokensFromSession handles errors gracefully', async () => {
    const { fetchSessionMarketHandoff } = await import('@/api/marketAccount')
    ;(fetchSessionMarketHandoff as any).mockRejectedValue(new Error('No session'))
    const { syncMarketTokensFromSession } = getComposable()
    // Should not throw
    await syncMarketTokensFromSession()
  })

  it('starts handoff after the profile owner is established without blocking startup on it', async () => {
    vi.mocked(authApi.validateSession).mockResolvedValue({ success: true, data: { valid: true } })
    let finishProfile!: () => void
    vi.spyOn(useAccountProfileStore(), 'refreshFromServer').mockReturnValue(new Promise(resolve => { finishProfile = resolve }))
    vi.mocked(fetchSessionMarketHandoff).mockImplementation(() => {
      expect(productReadAccountEpoch.value).toBe(ownerEpoch)
      return new Promise(() => {})
    })
    const startup = getComposable().ensureStartupAuthenticated()
    await flushPromises()
    expect(fetchSessionMarketHandoff).not.toHaveBeenCalled()
    const ownerEpoch = ++productReadAccountEpoch.value
    finishProfile()
    await expect(startup).resolves.toMatchObject({ ok: true })
    expect(fetchSessionMarketHandoff).toHaveBeenCalledTimes(1)
  })

  it.each(['success', 'unauthorized'])('retires an invalidated attempt without changing the auth epoch: %s', async outcome => {
    let settle!: (value: unknown) => void
    let current = true
    vi.mocked(authApi.validateSession).mockReturnValue(new Promise((resolve, reject) => { settle = outcome === 'success' ? resolve : reject }))
    const startup = getComposable().ensureStartupAuthenticated(() => current)
    current = false
    settle(outcome === 'success' ? { success: true } : { status: 401 })
    await expect(startup).resolves.toMatchObject({ ok: false })
    expect(mockRouter.replace).not.toHaveBeenCalled()
    expect(fetchSessionMarketHandoff).not.toHaveBeenCalled()
  })

  it('does not persist a late optional handoff from a retired attempt', async () => {
    let finish!: (value: unknown) => void
    let current = true
    vi.mocked(fetchSessionMarketHandoff).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const handoff = getComposable().syncMarketTokensFromSession(() => current)
    current = false
    finish({ synthetic: true })
    await handoff
    expect(persistMarketTokensFromHandoff).not.toHaveBeenCalled()
  })

  it.each(['timeout', 'cancel', 'retry'] as const)('ignores old invalid and rejected auth after %s and a successful retry', async action => {
    vi.useFakeTimers()
    vi.spyOn(useAccountProfileStore(), 'refreshFromServer').mockResolvedValue(undefined)
    for (const outcome of ['invalid', 'rejected']) {
      vi.clearAllMocks()
      let finish!: () => void
      vi.mocked(authApi.validateSession).mockReturnValueOnce(new Promise((resolve, reject) => {
        finish = () => outcome === 'invalid' ? resolve({ valid: false }) : reject(new Error('late validation failure'))
      })).mockResolvedValueOnce({ valid: true })
      const splash = useStartupSplash()
      const { ensureStartupAuthenticated } = getComposable()
      const task = async (current: () => boolean) => {
        const result = await ensureStartupAuthenticated(current)
        if (current() && !result.ok) throw new Error('unconfirmed session')
      }
      const old = splash.runStartup(task)
      if (action === 'timeout') await vi.advanceTimersByTimeAsync(STARTUP_READY_TIMEOUT_MS)
      if (action === 'cancel') splash.cancelStartup()
      await splash.runStartup(task)
      expect(splash.appReady.value).toBe(true)
      finish()
      await old
      expect(mockRouter.replace).not.toHaveBeenCalled()
      expect(mockDismiss).not.toHaveBeenCalled()
      expect(useAccountProfileStore().refreshFromServer).toHaveBeenCalledOnce()
      expect(fetchSessionMarketHandoff).toHaveBeenCalledOnce()
      splash.teardownOnUnmount()
    }
  })

  it.each(['timeout', 'cancel', 'retry', 'session'] as const)('does not persist a retired background handoff after %s', async action => {
    vi.useFakeTimers()
    vi.spyOn(useAccountProfileStore(), 'refreshFromServer').mockResolvedValue(undefined)
    vi.mocked(authApi.validateSession).mockResolvedValue({ valid: true })
    let finishHandoff!: () => void
    vi.mocked(fetchSessionMarketHandoff).mockReturnValue(new Promise(resolve => { finishHandoff = () => resolve(null) }))
    const splash = useStartupSplash()
    const { ensureStartupAuthenticated } = getComposable()
    let finishResource!: () => void
    const resource = new Promise<void>(resolve => { finishResource = resolve })
    const old = splash.runStartup(async current => {
      await ensureStartupAuthenticated(current)
      await resource
    })
    await flushPromises()
    expect(fetchSessionMarketHandoff).toHaveBeenCalledOnce()
    if (action === 'timeout') await vi.advanceTimersByTimeAsync(STARTUP_READY_TIMEOUT_MS)
    if (action === 'cancel') splash.cancelStartup()
    if (action === 'retry') await splash.runStartup(async () => {})
    if (action === 'session') invalidateEnterpriseSessionCache()
    finishHandoff()
    await flushPromises()
    expect(persistMarketTokensFromHandoff).not.toHaveBeenCalled()
    finishResource()
    await old
    splash.teardownOnUnmount()
  })

  it('allows the successful session background handoff to finish after workspace readiness', async () => {
    vi.spyOn(useAccountProfileStore(), 'refreshFromServer').mockResolvedValue(undefined)
    vi.mocked(authApi.validateSession).mockResolvedValue({ valid: true })
    let finishHandoff!: () => void
    vi.mocked(fetchSessionMarketHandoff).mockReturnValue(new Promise(resolve => { finishHandoff = () => resolve(null) }))
    const splash = useStartupSplash()
    const { ensureStartupAuthenticated } = getComposable()
    await splash.runStartup(async current => {
      const result = await ensureStartupAuthenticated(current)
      expect(result.ok).toBe(true)
    })
    expect(splash.appReady.value).toBe(true)
    expect(persistMarketTokensFromHandoff).not.toHaveBeenCalled()
    finishHandoff()
    await flushPromises()
    expect(persistMarketTokensFromHandoff).toHaveBeenCalledWith(null)
    splash.teardownOnUnmount()
  })

  it.each(['success', 'unauthorized'])('does not redirect or start handoff from an old startup %s', async outcome => {
    let settle!: (value: unknown) => void
    vi.mocked(authApi.validateSession).mockReturnValue(new Promise((resolve, reject) => { settle = outcome === 'success' ? resolve : reject }))
    const startup = getComposable().ensureStartupAuthenticated()
    invalidateEnterpriseSessionCache()
    settle(outcome === 'success' ? { success: true } : { status: 401 })
    await expect(startup).resolves.toMatchObject({ ok: false })
    expect(mockRouter.replace).not.toHaveBeenCalled()
    expect(fetchSessionMarketHandoff).not.toHaveBeenCalled()
  })
})

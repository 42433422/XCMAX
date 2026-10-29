import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useStartupAuth } from '@/composables/useStartupAuth'
import { flushPromises } from '@vue/test-utils'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { fetchSessionMarketHandoff } from '@/api/marketAccount'

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

  it('ensureStartupAuthenticated handles exception', async () => {
    ;(authApi.validateSession as any).mockRejectedValue(new Error('Network error'))
    const { ensureStartupAuthenticated } = getComposable()
    const result = await ensureStartupAuthenticated()
    expect(result.ok).toBe(false)
    expect(mockDismiss).toHaveBeenCalled()
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

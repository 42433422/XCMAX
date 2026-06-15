import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useStartupAuth } from '@/composables/useStartupAuth'

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
})

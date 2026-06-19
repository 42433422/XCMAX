import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from './auth'
import { api } from '../api'
import { ApiError } from '../infrastructure/http/client'
import { ACCESS_TOKEN_KEY } from '../infrastructure/storage/tokenStore'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../api', () => ({
  api: {
    login: vi.fn(),
    loginWithCode: vi.fn(),
    me: vi.fn(),
    paymentMyPlan: vi.fn(),
  },
  clearAuthTokens: vi.fn(() => localStorage.removeItem(ACCESS_TOKEN_KEY)),
}))

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
    vi.clearAllMocks()
  })

  it('refreshes the current user from the API when a token exists', async () => {
    setActivePinia(createPinia())
    localStorage.setItem(ACCESS_TOKEN_KEY, 'token-1')
    vi.mocked(api.me).mockResolvedValue({ id: 1, username: 'admin', is_admin: true })
    const store = useAuthStore()

    await store.refreshSession()

    expect(store.isLoggedIn).toBe(true)
    expect(store.isAdmin).toBe(true)
    expect(store.username).toBe('admin')
  })

  it('derives level from experience when nested Java me has no level_profile', async () => {
    setActivePinia(createPinia())
    localStorage.setItem(ACCESS_TOKEN_KEY, 'token-2')
    vi.mocked(api.me).mockResolvedValue({
      user: { id: 2, username: 'u2', email: 'u2@e.com', is_admin: false, experience: 0 },
    })
    const store = useAuthStore()
    await store.refreshSession()
    expect(store.levelProfile?.level).toBe(1)
    expect(store.levelProfile?.title).toBe('新手')
  })

  it('clears session state on logout', () => {
    setActivePinia(createPinia())
    localStorage.setItem(ACCESS_TOKEN_KEY, 'token-1')
    const store = useAuthStore()
    store.user = { id: 1, username: 'user' }

    store.logout()

    expect(store.isLoggedIn).toBe(false)
    expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull()
  })

  it('handles profile fallbacks, membership refresh, admin unlock, and cached sessions', async () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, 'token-3')
    vi.mocked(api.me).mockResolvedValue({
      id: 3,
      username: '   ',
      email: 'fallback@example.com',
      is_admin: false,
      level_profile: {
        level: 0,
        title: 123,
        experience: '5',
        current_level_min_exp: 2,
        next_level_min_exp: null,
        progress: 2,
      },
    })
    vi.mocked(api.paymentMyPlan).mockResolvedValue({
      membership: { tier: 'vip', is_member: true },
    })
    const store = useAuthStore()

    await store.refreshSession()
    expect(store.username).toBe('fallback')
    expect(store.levelProfile).toMatchObject({
      level: 1,
      title: '',
      nextLevelMinExp: null,
      progress: 1,
    })
    await store.refreshMembership()
    expect(store.membership).toEqual({ tier: 'vip', label: '', is_member: true })
    expect(store.membershipTier).toBe('vip')

    const future = new Date(Date.now() + 60_000).toISOString()
    store.setAdminDigestUnlock(future)
    expect(store.adminUiUnlocked).toBe(true)
    expect(sessionStorage.getItem('modstore_admin_digest_unlock_expires')).toBe(future)
    store.clearAdminDigestUnlock()
    expect(store.adminUiUnlocked).toBe(false)

    await store.refreshSession()
    expect(api.me).toHaveBeenCalledTimes(1)
  })

  it('handles membership and refresh failures without hiding auth rejection semantics', async () => {
    const store = useAuthStore()

    await store.refreshMembership()
    expect(store.membership).toBeNull()
    expect(store.membershipFetchFailed).toBe(false)

    localStorage.setItem(ACCESS_TOKEN_KEY, 'token-4')
    vi.mocked(api.paymentMyPlan).mockResolvedValueOnce({})
    await store.refreshMembership()
    expect(store.membership).toEqual({ tier: 'free', label: '普通用户', is_member: false })

    vi.mocked(api.paymentMyPlan).mockRejectedValueOnce(new Error('plan down'))
    await store.refreshMembership()
    expect(store.membership).toBeNull()
    expect(store.membershipFetchFailed).toBe(true)

    vi.mocked(api.me).mockResolvedValueOnce({ ok: false })
    await expect(store.refreshSession(true)).resolves.toBeNull()
    expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull()

    localStorage.setItem(ACCESS_TOKEN_KEY, 'token-5')
    vi.mocked(api.me).mockRejectedValueOnce(new ApiError('forbidden', 403))
    await expect(store.refreshSession(true)).resolves.toBeNull()
    expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull()

    localStorage.setItem(ACCESS_TOKEN_KEY, 'token-6')
    store.user = { id: 9, username: 'old' }
    vi.mocked(api.me).mockRejectedValueOnce(new Error('network down'))
    await expect(store.refreshSession(true)).resolves.toBeNull()
    expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBe('token-6')
    expect(store.user).toBeNull()
  })

  it('delegates password and code login then refreshes the session', async () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, 'token-7')
    vi.mocked(api.login).mockResolvedValue({ access_token: 'token-7' })
    vi.mocked(api.loginWithCode).mockResolvedValue({ access_token: 'token-8' })
    vi.mocked(api.me).mockResolvedValue({ id: 7, username: 'login-user' })
    const store = useAuthStore()

    await expect(store.loginWithPassword('u', 'p')).resolves.toEqual({ access_token: 'token-7' })
    expect(api.login).toHaveBeenCalledWith('u', 'p')
    await expect(store.loginWithCode('u@example.com', '123456')).resolves.toEqual({ access_token: 'token-8' })
    expect(api.loginWithCode).toHaveBeenCalledWith('u@example.com', '123456')
  })
})

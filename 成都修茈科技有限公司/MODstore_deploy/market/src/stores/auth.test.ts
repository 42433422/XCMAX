import { describe, expect, it, vi } from 'vitest'
import { useAuthStore } from './auth'
import { api } from '../api'
import { ACCESS_TOKEN_KEY } from '../infrastructure/storage/tokenStore'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../api', () => ({
  api: {
    login: vi.fn(),
    loginWithCode: vi.fn(),
    me: vi.fn(),
  },
  clearAuthTokens: vi.fn(() => localStorage.removeItem(ACCESS_TOKEN_KEY)),
}))

describe('auth store', () => {
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
})

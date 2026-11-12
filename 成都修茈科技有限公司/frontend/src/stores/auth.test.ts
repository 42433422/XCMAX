import { describe, expect, it, vi } from 'vitest'
import { useAuthStore } from './auth'
import { api } from '../api'

vi.mock('../api', () => ({
  api: {
    me: vi.fn(),
  },
}))

describe('auth store', () => {
  it('无 token 时 init 不发请求且 isLoggedIn 为 false', async () => {
    const store = useAuthStore()
    await store.init()
    expect(api.me).not.toHaveBeenCalled()
    expect(store.isLoggedIn).toBe(false)
    expect(store.user).toBeNull()
  })

  it('有 token 且 /me 成功后 user 与 isAdmin 正确填充', async () => {
    localStorage.setItem('modstore_token', 'tok-123')
    vi.mocked(api.me).mockResolvedValue({ id: 1, username: 'alice', is_admin: true })
    const store = useAuthStore()

    const me = await store.refreshSession(true)

    expect(me).toMatchObject({ username: 'alice', is_admin: true })
    expect(store.isLoggedIn).toBe(true)
    expect(store.isAdmin).toBe(true)
  })

  it('有 token 但 /me 失败：清空 token 与 session', async () => {
    localStorage.setItem('modstore_token', 'bad')
    vi.mocked(api.me).mockRejectedValue(new Error('401'))
    const store = useAuthStore()

    const me = await store.refreshSession(true)

    expect(me).toBeNull()
    expect(localStorage.getItem('modstore_token')).toBeNull()
    expect(store.isLoggedIn).toBe(false)
  })

  it('15 秒内重复 refreshSession 命中缓存，不再请求 /me', async () => {
    localStorage.setItem('modstore_token', 'tok-456')
    vi.mocked(api.me).mockResolvedValue({ id: 2, username: 'bob' })
    const store = useAuthStore()

    await store.refreshSession(true)
    await store.refreshSession(false)

    expect(api.me).toHaveBeenCalledTimes(1)
  })

  it('logout 清空 user/token/mode', () => {
    localStorage.setItem('modstore_token', 'x')
    const store = useAuthStore()
    store.setMode('admin')

    store.logout()

    expect(localStorage.getItem('modstore_token')).toBeNull()
    expect(store.user).toBeNull()
    expect(store.currentMode).toBe('client')
  })

  it('hasToken 拒绝字面 "undefined"/"null"/空串', () => {
    const store = useAuthStore()
    localStorage.setItem('modstore_token', 'undefined')
    expect(store.hasToken()).toBe(false)
    localStorage.setItem('modstore_token', 'null')
    expect(store.hasToken()).toBe(false)
    localStorage.setItem('modstore_token', '')
    expect(store.hasToken()).toBe(false)
    localStorage.setItem('modstore_token', 'real')
    expect(store.hasToken()).toBe(true)
  })
})

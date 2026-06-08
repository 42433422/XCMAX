import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installAuthGuards } from './guards'
import { ACCESS_TOKEN_KEY } from '../infrastructure/storage/tokenStore'

vi.mock('../api', () => ({
  api: {
    me: vi.fn(),
  },
  clearAuthTokens: vi.fn(() => localStorage.removeItem(ACCESS_TOKEN_KEY)),
}))

import { api } from '../api'

function installAndGetGuard() {
  let guard: any
  installAuthGuards({
    beforeEach(fn: any) {
      guard = fn
    },
  } as any)
  return guard
}

describe('auth router guards', () => {
  beforeEach(() => {
    vi.mocked(api.me).mockReset()
  })

  it('redirects legacy home hash to AI store', async () => {
    const guard = installAndGetGuard()

    await expect(guard({ name: 'home', hash: '#ai-market', meta: {}, query: {}, fullPath: '/' })).resolves.toEqual({
      name: 'ai-store',
      replace: true,
    })
  })

  it('redirects protected routes to login when there is no token', async () => {
    const guard = installAndGetGuard()

    await expect(
      guard({ name: 'wallet', hash: '', meta: { auth: true }, query: {}, fullPath: '/wallet' }),
    ).resolves.toEqual({ name: 'login', query: { redirect: '/wallet' } })
  })

  it('validates guest redirects and blocks open redirects', async () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, 'token-1')
    vi.mocked(api.me).mockResolvedValue({ id: 1, username: 'user' })
    const guard = installAndGetGuard()

    await expect(
      guard({
        name: 'login',
        hash: '',
        meta: {},
        query: { redirect: '//evil.example' },
        fullPath: '/login',
      }),
    ).resolves.toBe('/workbench/home')
  })

  it('normalizes market-prefixed and official-site redirects after auth', async () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, 'token-1')
    vi.mocked(api.me).mockResolvedValue({ id: 1, username: 'user' })
    const guard = installAndGetGuard()

    await expect(
      guard({
        name: 'login',
        hash: '',
        meta: {},
        query: { redirect: '/market/wallet' },
        fullPath: '/login',
      }),
    ).resolves.toBe('/wallet')

    await expect(
      guard({
        name: 'login',
        hash: '',
        meta: {},
        query: { redirect: '/index.html' },
        fullPath: '/login',
      }),
    ).resolves.toBe('/workbench/home')
  })

  it('sends non-admin users away from admin routes', async () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, 'token-1')
    vi.mocked(api.me).mockResolvedValue({ id: 1, username: 'user', is_admin: false })
    const guard = installAndGetGuard()

    await expect(
      guard({ name: 'admin-database', hash: '', meta: { admin: true }, query: {}, fullPath: '/admin/database' }),
    ).resolves.toEqual({ name: 'home' })
  })
})

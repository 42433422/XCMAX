import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({
  token: false,
  admin: false,
  refreshResult: null as null | { id: number },
  hasToken: vi.fn(() => auth.token),
  refreshSession: vi.fn(async () => auth.refreshResult),
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => ({
    hasToken: auth.hasToken,
    refreshSession: auth.refreshSession,
    get isAdmin() {
      return auth.admin
    },
  }),
}))

import router from './index'

describe('application router', () => {
  beforeEach(async () => {
    auth.token = false
    auth.admin = false
    auth.refreshResult = null
    auth.hasToken.mockClear()
    auth.refreshSession.mockClear()
    await router.push('/')
  })

  afterEach(() => {
    window.history.replaceState({}, '', '/')
  })

  it('redirects the legacy market hash to the dedicated store', async () => {
    await router.push('/#ai-market')
    expect(router.currentRoute.value.name).toBe('ai-store')
  })

  it('sends unauthenticated users to login and preserves the destination', async () => {
    await router.push('/wallet')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/wallet')
  })

  it.each([
    ['/login?redirect=/wallet', '/wallet'],
    ['/login?redirect=//evil.example', '/'],
    ['/login?redirect=/login-email', '/'],
    ['/login?redirect=https://evil.example', '/'],
    ['/register', '/workbench/repository'],
  ])('routes authenticated guests safely: %s', async (source, expected) => {
    auth.token = true
    auth.refreshResult = { id: 1 }
    await router.push(source)
    expect(router.currentRoute.value.fullPath).toBe(expected)
  })

  it('keeps a guest page when the stored session cannot be refreshed', async () => {
    auth.token = true
    auth.refreshResult = null
    await router.push('/login-email')
    expect(router.currentRoute.value.name).toBe('login-email')
  })

  it('requires both a current session and admin role', async () => {
    auth.token = true
    await router.push('/admin/database')
    expect(router.currentRoute.value.name).toBe('login')

    auth.refreshResult = { id: 1 }
    await router.push('/admin/database')
    expect(router.currentRoute.value.name).toBe('home')

    auth.admin = true
    await router.push('/admin/database')
    expect(router.currentRoute.value.name).toBe('admin-database')
  })

  it('keeps compatibility redirects within the workbench', async () => {
    auth.token = true
    auth.refreshResult = { id: 1 }
    await router.push('/repository')
    expect(router.currentRoute.value.fullPath).toBe('/workbench/repository')
    await router.push('/repository/mod/demo')
    expect(router.currentRoute.value.fullPath).toBe('/workbench/mod/demo')
  })

  it('returns saved, hash, and top scroll positions', () => {
    const scroll = router.options.scrollBehavior!
    const saved = { left: 5, top: 10 }
    expect(scroll({} as never, {} as never, saved)).toEqual(saved)
    expect(scroll({ hash: '#plans' } as never, {} as never, null)).toEqual({
      el: '#plans',
      behavior: 'smooth',
    })
    expect(scroll({ hash: '' } as never, {} as never, null)).toEqual({ top: 0 })
  })
})

import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  validateEnterpriseSessionCached,
  consumeDesktopSessionBootstrapHint,
  hasRecentEnterpriseSessionHint,
  invalidateEnterpriseSessionCache,
  LS_ENTERPRISE_SESSION_HINT,
  markEnterpriseSessionValid,
} from './authSessionCache'

vi.mock('@/api/auth', () => ({
  authApi: {
    validateSession: vi.fn(),
  },
}))

import { authApi } from '@/api/auth'

describe('authSessionCache', () => {
  beforeEach(() => {
    localStorage.clear()
    invalidateEnterpriseSessionCache()
    vi.mocked(authApi.validateSession).mockReset()
  })

  it('caches valid session within TTL', async () => {
    vi.mocked(authApi.validateSession).mockResolvedValue({ success: true })
    await expect(validateEnterpriseSessionCached()).resolves.toBe(true)
    await expect(validateEnterpriseSessionCached()).resolves.toBe(true)
    expect(authApi.validateSession).toHaveBeenCalledTimes(1)
  })

  it('forces refresh when requested', async () => {
    vi.mocked(authApi.validateSession).mockResolvedValue({ valid: true })
    await validateEnterpriseSessionCached()
    await validateEnterpriseSessionCached(true)
    expect(authApi.validateSession).toHaveBeenCalledTimes(2)
  })

  it('invalidate clears cache', async () => {
    vi.mocked(authApi.validateSession).mockResolvedValue({ data: { valid: true } })
    await validateEnterpriseSessionCached()
    invalidateEnterpriseSessionCache()
    await validateEnterpriseSessionCached()
    expect(authApi.validateSession).toHaveBeenCalledTimes(2)
  })

  it('trusts the freshly established login session without a blocking probe', async () => {
    markEnterpriseSessionValid()
    await expect(validateEnterpriseSessionCached()).resolves.toBe(true)
    expect(authApi.validateSession).not.toHaveBeenCalled()
    expect(hasRecentEnterpriseSessionHint()).toBe(true)
  })

  it('keeps only a short-lived local shell-entry hint after official validation', async () => {
    vi.mocked(authApi.validateSession).mockResolvedValue({ success: true })
    await expect(validateEnterpriseSessionCached()).resolves.toBe(true)
    expect(hasRecentEnterpriseSessionHint()).toBe(true)
    expect(hasRecentEnterpriseSessionHint(Date.now() + 24 * 60 * 60_000 + 1)).toBe(false)
    expect(localStorage.getItem(LS_ENTERPRISE_SESSION_HINT)).toBeNull()
  })

  it('clears the shell-entry hint after an explicit cache invalidation', () => {
    markEnterpriseSessionValid()
    expect(hasRecentEnterpriseSessionHint()).toBe(true)
    invalidateEnterpriseSessionCache()
    expect(hasRecentEnterpriseSessionHint()).toBe(false)
  })

  it('shares Electron persisted-cookie entry hint across the initial navigation only', async () => {
    const consumeBootstrapSessionHint = vi.fn().mockResolvedValue(true)
    Object.defineProperty(window, 'xcagiDesktop', {
      configurable: true,
      value: { consumeBootstrapSessionHint },
    })

    await expect(consumeDesktopSessionBootstrapHint()).resolves.toBe(true)
    await expect(consumeDesktopSessionBootstrapHint()).resolves.toBe(true)
    expect(consumeBootstrapSessionHint).toHaveBeenCalledOnce()

    invalidateEnterpriseSessionCache()
    Object.defineProperty(window, 'xcagiDesktop', { configurable: true, value: undefined })
    await expect(consumeDesktopSessionBootstrapHint()).resolves.toBe(false)
  })
  it.each([new Error('network'), Object.assign(new Error('timeout'), { name: 'AbortError' }), Object.assign(new Error('unavailable'), { status: 503 })])('keeps an outage unknown rather than caching an authenticated or invalid session', async error => {
    markEnterpriseSessionValid()
    vi.mocked(authApi.validateSession).mockRejectedValue(error)
    await expect(validateEnterpriseSessionCached(true)).rejects.toBe(error)
    expect(hasRecentEnterpriseSessionHint()).toBe(true)
    await expect(validateEnterpriseSessionCached(true)).rejects.toBe(error)
    expect(authApi.validateSession).toHaveBeenCalledTimes(2)
  })

  it.each([{ valid: false }, { success: true, valid: false }, { status: 401 }, { status: 403 }])('honors definitive invalidity: %s', async response => {
    markEnterpriseSessionValid()
    if ('status' in response) vi.mocked(authApi.validateSession).mockRejectedValue(response)
    else vi.mocked(authApi.validateSession).mockResolvedValue(response)
    await expect(validateEnterpriseSessionCached(true)).resolves.toBe(false)
    expect(hasRecentEnterpriseSessionHint()).toBe(false)
  })

  it('coalesces concurrent validation and ignores its result after a new login', async () => {
    let finish!: (value: unknown) => void
    vi.mocked(authApi.validateSession).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const first = validateEnterpriseSessionCached()
    const second = validateEnterpriseSessionCached()
    expect(authApi.validateSession).toHaveBeenCalledOnce()
    markEnterpriseSessionValid()
    finish({ valid: false })
    await expect(first).resolves.toBe(true)
    await expect(second).resolves.toBe(true)
    expect(hasRecentEnterpriseSessionHint()).toBe(true)
  })

})

 it('retains the desktop shell when profile refresh is temporarily unavailable', async () => {
  const { refreshDesktopSessionInBackground } = await import('./desktopSessionRestore')
  vi.mocked(authApi.validateSession).mockResolvedValue({ valid: true })
  const replace = vi.fn()
  const profile = { loaded: false, sessionCheckUnavailable: true, refreshFromServer: vi.fn().mockResolvedValue(undefined) }
  refreshDesktopSessionInBackground({ replace }, profile, '/settings')
  await vi.waitFor(() => expect(profile.refreshFromServer).toHaveBeenCalledOnce())
  expect(replace).not.toHaveBeenCalled()
 })

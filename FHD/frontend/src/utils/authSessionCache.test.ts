import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  validateEnterpriseSessionCached,
  canResumeRecentDesktopSession,
  consumeDesktopSessionBootstrapHint,
  hasRecentEnterpriseSessionHint,
  hasKnownEnterpriseSession,
  invalidateEnterpriseSessionCache,
  LS_ENTERPRISE_SESSION_HINT,
  markEnterpriseSessionValid,
  probeEnterpriseSession,
} from './authSessionCache'

vi.mock('@/api/auth', () => ({
  authApi: {
    validateSession: vi.fn(),
  },
}))

import { authApi } from '@/api/auth'
import { productReadAccountEpoch } from './productReadAccountScope'

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

  it('reports whether a known session exists without asking the server', () => {
    expect(hasKnownEnterpriseSession()).toBe(false)
    markEnterpriseSessionValid()
    expect(hasKnownEnterpriseSession()).toBe(true)
    invalidateEnterpriseSessionCache()
    expect(hasKnownEnterpriseSession()).toBe(false)
    localStorage.setItem(LS_ENTERPRISE_SESSION_HINT, String(Date.now()))
    expect(hasKnownEnterpriseSession()).toBe(true)
  })

  it('reuses a valid session after the short TTL and refreshes behind the click', async () => {
    const now = 1_700_000_000_000
    vi.spyOn(Date, 'now').mockReturnValue(now)
    vi.mocked(authApi.validateSession).mockResolvedValue({ valid: true })
    await expect(validateEnterpriseSessionCached()).resolves.toBe(true)
    vi.spyOn(Date, 'now').mockReturnValue(now + 6 * 60_000)
    await expect(validateEnterpriseSessionCached()).resolves.toBe(true)
    await vi.waitFor(() => expect(authApi.validateSession).toHaveBeenCalledTimes(2))
    vi.restoreAllMocks()
  })

  it('reuses a definitive invalid session inside the short TTL', async () => {
    vi.mocked(authApi.validateSession).mockResolvedValue({ valid: false })
    await expect(validateEnterpriseSessionCached()).resolves.toBe(false)
    await expect(validateEnterpriseSessionCached()).resolves.toBe(false)
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

  it('resumes a persisted desktop session even when the login URL still has an old error', async () => {
    localStorage.setItem(LS_ENTERPRISE_SESSION_HINT, String(Date.now()))
    await expect(canResumeRecentDesktopSession(true, true, { error: '用户名或密码错误' })).resolves.toBe(true)
  })

  it.each([false, true])('requires explicit login without consuming a desktop hint (local hint: %s)', async (localHint) => {
    const consumeBootstrapSessionHint = vi.fn().mockResolvedValue(true)
    vi.stubGlobal('xcagiDesktop', { consumeBootstrapSessionHint })
    try {
      if (localHint) localStorage.setItem(LS_ENTERPRISE_SESSION_HINT, String(Date.now()))
      await expect(canResumeRecentDesktopSession(true, true, { reauthenticate: '1' })).resolves.toBe(false)
      expect(consumeBootstrapSessionHint).not.toHaveBeenCalled()
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('waits out a 12s model-backed ELT call before the desktop session probe reports failure', async () => {
    vi.mocked(authApi.validateSession).mockResolvedValueOnce({ valid: true })
    await expect(probeEnterpriseSession()).resolves.toBe('valid')
    const timeoutMs = vi.mocked(authApi.validateSession).mock.calls[0]?.[0]?.timeoutMs
    expect(timeoutMs).toBeGreaterThan(12_000)
  })

  it('sends the shell to login when the server says the session is gone, and not on a network miss', async () => {
    const events: string[] = []
    const onInvalid = () => events.push('invalid')
    window.addEventListener('xcagi:enterprise-session-invalid', onInvalid)
    vi.mocked(authApi.validateSession).mockResolvedValueOnce({ valid: false })
    await expect(probeEnterpriseSession()).resolves.toBe('invalid')
    expect(events).toEqual(['invalid'])
    vi.mocked(authApi.validateSession).mockRejectedValueOnce(new Error('Failed to fetch'))
    await expect(probeEnterpriseSession()).resolves.toBe('unknown')
    expect(events).toEqual(['invalid'])
    window.removeEventListener('xcagi:enterprise-session-invalid', onInvalid)
  })

  it('does not reuse another account scope cache or pending validation', async () => {
    markEnterpriseSessionValid()
    let finish!: (value: unknown) => void
    vi.mocked(authApi.validateSession).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const oldProbe = probeEnterpriseSession()
    productReadAccountEpoch.value += 1
    vi.mocked(authApi.validateSession).mockResolvedValueOnce({ valid: true })
    await expect(validateEnterpriseSessionCached()).resolves.toBe(true)
    expect(authApi.validateSession).toHaveBeenCalledTimes(2)
    const invalid = vi.spyOn(window, 'dispatchEvent')
    finish({ valid: false })
    await expect(oldProbe).resolves.toBe('unknown')
    expect(invalid).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'xcagi:enterprise-session-invalid' }))
    expect(hasRecentEnterpriseSessionHint()).toBe(true)
    invalid.mockRestore()
  })

  it('retires a probe across logout even before another login is established', async () => {
    let finish!: (value: unknown) => void
    vi.mocked(authApi.validateSession).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const pending = probeEnterpriseSession()
    invalidateEnterpriseSessionCache()
    const invalid = vi.spyOn(window, 'dispatchEvent')
    finish({ valid: false })
    await expect(pending).resolves.toBe('unknown')
    expect(invalid).not.toHaveBeenCalled()
    invalid.mockRestore()
  })

  it('does not restore an old Electron bootstrap hint after logout', async () => {
    let finish!: (value: boolean) => void
    Object.defineProperty(window, 'xcagiDesktop', { configurable: true, value: {
      consumeBootstrapSessionHint: () => new Promise<boolean>(resolve => { finish = resolve }),
    } })
    const pending = consumeDesktopSessionBootstrapHint()
    invalidateEnterpriseSessionCache()
    finish(true)
    await expect(pending).resolves.toBe(false)
    Object.defineProperty(window, 'xcagiDesktop', { configurable: true, value: undefined })
  })

  it('lets the new desktop owner validate while an old background refresh is pending', async () => {
    const { refreshDesktopSessionInBackground } = await import('./desktopSessionRestore')
    let finish!: (value: unknown) => void
    vi.mocked(authApi.validateSession).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const router = { replace: vi.fn().mockResolvedValue(undefined) }
    const previous = { loaded: false, refreshFromServer: vi.fn().mockResolvedValue(undefined) }
    const current = { loaded: false, refreshFromServer: vi.fn().mockResolvedValue(undefined) }
    refreshDesktopSessionInBackground(router, previous, '/old-workspace')
    productReadAccountEpoch.value += 1
    vi.mocked(authApi.validateSession).mockResolvedValueOnce({ valid: true })
    refreshDesktopSessionInBackground(router, current, '/new-workspace')
    await vi.waitFor(() => expect(current.refreshFromServer).toHaveBeenCalledOnce())
    finish({ valid: false })
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(router.replace).not.toHaveBeenCalled()
    expect(previous.refreshFromServer).not.toHaveBeenCalled()
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

 it('does not log out a valid session whose workspace hydration has not published yet', async () => {
  const { refreshDesktopSessionInBackground } = await import('./desktopSessionRestore')
  vi.mocked(authApi.validateSession).mockResolvedValue({ success: true, data: { valid: true } })
  const replace = vi.fn()
  const profile = { loaded: false, sessionCheckUnavailable: false, refreshFromServer: vi.fn().mockResolvedValue(undefined) }
  refreshDesktopSessionInBackground({ replace }, profile, '/')
  await vi.waitFor(() => expect(profile.refreshFromServer).toHaveBeenCalledOnce())
  expect(replace).not.toHaveBeenCalled()
 })

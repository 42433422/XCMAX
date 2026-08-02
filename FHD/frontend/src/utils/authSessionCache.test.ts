import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  validateEnterpriseSessionCached,
  invalidateEnterpriseSessionCache,
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
  })

  it('ignores a stale invalid probe that started before login completed', async () => {
    let resolveProbe!: (value: { success: boolean }) => void
    vi.mocked(authApi.validateSession).mockReturnValue(
      new Promise((resolve) => {
        resolveProbe = resolve
      }),
    )

    const staleProbe = validateEnterpriseSessionCached()
    markEnterpriseSessionValid()
    resolveProbe({ success: false })

    await expect(staleProbe).resolves.toBe(true)
    await expect(validateEnterpriseSessionCached()).resolves.toBe(true)
    expect(authApi.validateSession).toHaveBeenCalledTimes(1)
  })
})

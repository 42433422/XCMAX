import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  validateEnterpriseSessionCached,
  invalidateEnterpriseSessionCache,
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
})

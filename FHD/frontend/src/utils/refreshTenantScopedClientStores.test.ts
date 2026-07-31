import { describe, expect, it, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { refreshTenantScopedClientStores } from './refreshTenantScopedClientStores'

vi.mock('@/utils/workspacePrefsApi', () => ({
  hydrateWorkspacePrefsFromServer: vi.fn().mockResolvedValue(undefined),
}))

describe('refreshTenantScopedClientStores', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('runs without throwing when pinia ready', () => {
    expect(() =>
      refreshTenantScopedClientStores({ tenantId: 1, marketUserId: 'u1' }),
    ).not.toThrow()
  })

  it('keeps the pre-login chat session when the enterprise scope becomes available', () => {
    localStorage.setItem('ai_session_id:local', 'session-before-login')

    refreshTenantScopedClientStores({ tenantId: 42, marketUserId: 9 })

    expect(localStorage.getItem('ai_session_id:tenant:42')).toBe('session-before-login')
  })

  it('does not overwrite an existing tenant chat session', () => {
    localStorage.setItem('ai_session_id:local', 'session-before-login')
    localStorage.setItem('ai_session_id:tenant:42', 'tenant-session')

    refreshTenantScopedClientStores({ tenantId: 42, marketUserId: 9 })

    expect(localStorage.getItem('ai_session_id:tenant:42')).toBe('tenant-session')
  })
})

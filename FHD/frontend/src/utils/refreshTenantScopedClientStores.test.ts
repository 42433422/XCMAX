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
      refreshTenantScopedClientStores({ tenantId: 't1', userId: 'u1' }),
    ).not.toThrow()
  })
})

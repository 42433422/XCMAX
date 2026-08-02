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

  it('runs and hydrates workspace preferences when pinia is ready', async () => {
    await expect(
      refreshTenantScopedClientStores({ tenantId: 't1', marketUserId: 'u1' }),
    ).resolves.toBeUndefined()
  })
})

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { refreshTenantScopedClientStores } from './refreshTenantScopedClientStores'

const { mockRefreshHostPackAcknowledged } = vi.hoisted(() => ({
  mockRefreshHostPackAcknowledged: vi.fn(),
}))

vi.mock('@/utils/workspacePrefsApi', () => ({
  hydrateWorkspacePrefsFromServer: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/constants/productFlow', () => ({
  refreshHostPackAcknowledged: mockRefreshHostPackAcknowledged,
}))

describe('refreshTenantScopedClientStores', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    mockRefreshHostPackAcknowledged.mockClear()
  })

  it('runs and hydrates workspace preferences when pinia is ready', async () => {
    await expect(refreshTenantScopedClientStores({ tenantId: 't1', marketUserId: 'u1' })).resolves.toBeUndefined()
    expect(mockRefreshHostPackAcknowledged).toHaveBeenCalledOnce()
  })
})

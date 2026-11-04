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

  it('retries once when the scope generation moves during prefs and still finishes', async () => {
    const { hydrateWorkspacePrefsFromServer } = await import('@/utils/workspacePrefsApi')
    const { updateProductReadAccountScope } = await import('./productReadAccountScope')
    vi.mocked(hydrateWorkspacePrefsFromServer).mockImplementationOnce(async () => {
      updateProductReadAccountScope({ tenantId: 2, marketUserId: 2, accountKind: 'enterprise' })
      return {}
    })
    await expect(refreshTenantScopedClientStores({ tenantId: 1, marketUserId: 1, accountKind: 'enterprise' })).resolves.toBeUndefined()
    expect(hydrateWorkspacePrefsFromServer).toHaveBeenCalledTimes(2)
    expect(mockRefreshHostPackAcknowledged).toHaveBeenCalledOnce()
  })
})

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

  it('does not retry an old scope when the generation moves during prefs', async () => {
    const { hydrateWorkspacePrefsFromServer } = await import('@/utils/workspacePrefsApi')
    const { updateProductReadAccountScope } = await import('./productReadAccountScope')
    vi.mocked(hydrateWorkspacePrefsFromServer).mockImplementationOnce(async () => {
      updateProductReadAccountScope({ tenantId: 2, marketUserId: 2, accountKind: 'enterprise' })
      return {}
    })
    await expect(refreshTenantScopedClientStores({ tenantId: 1, marketUserId: 1, accountKind: 'enterprise' })).resolves.toBeUndefined()
    expect(hydrateWorkspacePrefsFromServer).toHaveBeenCalledTimes(1)
    expect(mockRefreshHostPackAcknowledged).not.toHaveBeenCalled()
  })
})

it('keeps B active after an older A hydration completes', async () => {
  setActivePinia(createPinia())
  const { hydrateWorkspacePrefsFromServer } = await import('@/utils/workspacePrefsApi')
  const { productReadAccountEpoch } = await import('./productReadAccountScope')
  let finishA!: () => void
  const aPending = new Promise<void>(resolve => { finishA = resolve })
  vi.mocked(hydrateWorkspacePrefsFromServer).mockReset()
  vi.mocked(hydrateWorkspacePrefsFromServer).mockImplementationOnce(async () => { await aPending; return {} })
  vi.mocked(hydrateWorkspacePrefsFromServer).mockResolvedValue({})
  const a = refreshTenantScopedClientStores({ tenantId: 1001, marketUserId: 1001 })
  await refreshTenantScopedClientStores({ tenantId: 2002, marketUserId: 2002 })
  const epochAfterB = productReadAccountEpoch.value
  finishA()
  await a
  expect(productReadAccountEpoch.value).toBe(epochAfterB)
})

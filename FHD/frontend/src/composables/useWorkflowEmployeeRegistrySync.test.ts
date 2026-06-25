import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const syncEnterpriseWorkflowRegistryMock = vi.fn()
vi.mock('@/utils/syncEnterpriseWorkflowRegistry', () => ({
  syncEnterpriseWorkflowRegistry: (...args: unknown[]) => syncEnterpriseWorkflowRegistryMock(...args),
}))

import { useWorkflowEmployeeRegistrySync } from './useWorkflowEmployeeRegistrySync'

describe('useWorkflowEmployeeRegistrySync', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    syncEnterpriseWorkflowRegistryMock.mockReset()
    syncEnterpriseWorkflowRegistryMock.mockResolvedValue({})
  })

  it('returns syncRegistry function', () => {
    const sync = useWorkflowEmployeeRegistrySync()
    expect(typeof sync.syncRegistry).toBe('function')
  })

  it('syncRegistry calls syncEnterpriseWorkflowRegistry with modsForWorkflowUi', async () => {
    const sync = useWorkflowEmployeeRegistrySync()
    await sync.syncRegistry()
    // syncRegistry 内部会先 await modsStore.initialize(true) 再 sync
    expect(syncEnterpriseWorkflowRegistryMock).toHaveBeenCalled()
  })

  it('syncRegistry does not throw when underlying sync fails', async () => {
    syncEnterpriseWorkflowRegistryMock.mockRejectedValueOnce(new Error('net'))
    const sync = useWorkflowEmployeeRegistrySync()
    await expect(sync.syncRegistry()).rejects.toThrow('net')
  })

  it('syncRegistry resolves when sync succeeds', async () => {
    syncEnterpriseWorkflowRegistryMock.mockResolvedValueOnce({ id: 'stack' })
    const sync = useWorkflowEmployeeRegistrySync()
    await expect(sync.syncRegistry()).resolves.toBeUndefined()
  })
})

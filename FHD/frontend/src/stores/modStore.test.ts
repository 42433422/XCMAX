import { describe, expect, it, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useModStoreStore } from './modStore'

vi.mock('@/api/modStore', () => ({
  getModCatalog: vi.fn(),
  getModDetails: vi.fn(),
  searchMods: vi.fn(),
}))

import * as modStoreApi from '@/api/modStore'

describe('useModStoreStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(modStoreApi.getModCatalog).mockReset()
    vi.mocked(modStoreApi.getModDetails).mockReset()
  })

  it('loads catalog and exposes computed lists', async () => {
    vi.mocked(modStoreApi.getModCatalog).mockResolvedValue({
      installed: [{ id: 'a', name: 'A', is_installed: true } as never],
      available: [{ id: 'b', name: 'B' } as never],
      indexed_count: 2,
    })
    const store = useModStoreStore()
    await store.loadCatalog()
    expect(store.installedCount).toBe(1)
    expect(store.availableCount).toBe(1)
    expect(store.allMods.map((m) => m.id).sort()).toEqual(['a', 'b'])
  })

  it('records load errors', async () => {
    vi.mocked(modStoreApi.getModCatalog).mockRejectedValue(new Error('net'))
    const store = useModStoreStore()
    await store.loadCatalog()
    expect(store.error).toBe('net')
    expect(store.loading).toBe(false)
  })

  it('loads mod details', async () => {
    vi.mocked(modStoreApi.getModDetails).mockResolvedValue({
      id: 'z',
      name: 'Z',
      version: '1',
      author: '',
      description: '',
      statistics: null,
      ratings: [],
      rating_count: 0,
    })
    const store = useModStoreStore()
    const d = await store.loadModDetails('z')
    expect(d?.id).toBe('z')
    expect(store.modDetails?.name).toBe('Z')
  })
})

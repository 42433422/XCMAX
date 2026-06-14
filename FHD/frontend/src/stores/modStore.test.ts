import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const apiMock = vi.hoisted(() => ({
  getModCatalog: vi.fn(),
  getModDetails: vi.fn(),
  installMod: vi.fn(),
  uninstallMod: vi.fn(),
  updateMod: vi.fn(),
  uploadModPackage: vi.fn(),
  searchMods: vi.fn(),
  getPopularMods: vi.fn(),
  getRecentMods: vi.fn(),
  checkUpdates: vi.fn(),
  rateMod: vi.fn(),
}))
vi.mock('@/api/modStore', () => apiMock)

import { useModStoreStore } from './modStore'

beforeEach(() => {
  setActivePinia(createPinia())
  for (const fn of Object.values(apiMock)) fn.mockReset()
})

describe('modStore computeds', () => {
  it('merges installed + available into allMods with is_installed flag', () => {
    const store = useModStoreStore()
    store.modCatalog = {
      installed: [{ id: 'a' }, { id: 'c' }],
      available: [{ id: 'a' }, { id: 'b' }],
      indexed_count: 3,
    } as never
    const all = store.allMods
    expect(all).toHaveLength(3)
    expect(all.find((m) => m.id === 'a')?.is_installed).toBe(true)
    expect(all.find((m) => m.id === 'c')?.is_installed).toBe(true)
    expect(all.find((m) => m.id === 'b')?.is_installed).toBeUndefined()
    expect(store.installedCount).toBe(2)
    expect(store.availableCount).toBe(2)
  })

  it('empty catalog yields empty lists', () => {
    const store = useModStoreStore()
    expect(store.installedMods).toEqual([])
    expect(store.availableMods).toEqual([])
    expect(store.allMods).toEqual([])
  })
})

describe('modStore actions success', () => {
  it('loadCatalog stores result', async () => {
    apiMock.getModCatalog.mockResolvedValue({ installed: [], available: [{ id: 'x' }], indexed_count: 1 })
    const store = useModStoreStore()
    await store.loadCatalog()
    expect(store.availableMods).toHaveLength(1)
    expect(store.loading).toBe(false)
  })

  it('loadModDetails returns details', async () => {
    apiMock.getModDetails.mockResolvedValue({ id: 'x' })
    const store = useModStoreStore()
    const d = await store.loadModDetails('x')
    expect(d).toEqual({ id: 'x' })
  })

  it('install/uninstall/update/upload reload catalog', async () => {
    apiMock.getModCatalog.mockResolvedValue({ installed: [], available: [], indexed_count: 0 })
    apiMock.installMod.mockResolvedValue({ ok: true })
    apiMock.uninstallMod.mockResolvedValue({ ok: true })
    apiMock.updateMod.mockResolvedValue({ ok: true })
    apiMock.uploadModPackage.mockResolvedValue({ ok: true })
    const store = useModStoreStore()
    await store.installModAction('pkg')
    await store.uninstallModAction('m')
    await store.updateModAction('m', 'pkg')
    await store.uploadModAction(new File(['x'], 'm.zip'), true)
    expect(apiMock.getModCatalog).toHaveBeenCalledTimes(4)
  })

  it('search/popular/recent populate catalog', async () => {
    apiMock.searchMods.mockResolvedValue({ data: [{ id: 's' }], count: 1 })
    apiMock.getPopularMods.mockResolvedValue([{ id: 'p' }])
    apiMock.getRecentMods.mockResolvedValue([{ id: 'r' }])
    const store = useModStoreStore()
    await store.searchModsAction('q')
    expect(store.availableMods[0].id).toBe('s')
    await store.getPopularModsAction()
    expect(store.availableMods[0].id).toBe('p')
    await store.getRecentModsAction()
    expect(store.availableMods[0].id).toBe('r')
  })

  it('checkUpdates and rateMod delegate', async () => {
    apiMock.checkUpdates.mockResolvedValue({ updates: [] })
    apiMock.rateMod.mockResolvedValue({ ok: true })
    apiMock.getModDetails.mockResolvedValue({ id: 'm' })
    const store = useModStoreStore()
    await store.checkUpdatesAction()
    await store.rateModAction('m', 5)
    expect(apiMock.rateMod).toHaveBeenCalled()
    expect(apiMock.getModDetails).toHaveBeenCalledWith('m')
  })
})

describe('modStore actions error', () => {
  it('loadCatalog records error message', async () => {
    apiMock.getModCatalog.mockRejectedValue(new Error('boom'))
    const store = useModStoreStore()
    await store.loadCatalog()
    expect(store.error).toBe('boom')
  })

  it('loadModDetails rethrows and records', async () => {
    apiMock.getModDetails.mockRejectedValue(new Error('det'))
    const store = useModStoreStore()
    await expect(store.loadModDetails('x')).rejects.toThrow('det')
    expect(store.error).toBe('det')
  })

  it('install rethrows and records non-error fallback', async () => {
    apiMock.installMod.mockRejectedValue('weird')
    const store = useModStoreStore()
    await expect(store.installModAction('p')).rejects.toBe('weird')
    expect(store.error).toBe('安装失败')
  })

  it('clearError and reset clear state', () => {
    const store = useModStoreStore()
    store.error = 'x'
    store.clearError()
    expect(store.error).toBeNull()
    store.modCatalog = { installed: [], available: [], indexed_count: 0 } as never
    store.reset()
    expect(store.modCatalog).toBeNull()
  })
})

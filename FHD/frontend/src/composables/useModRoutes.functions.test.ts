import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { ref } from 'vue'

const mockModsForUiRef = ref<unknown[]>([])

const { mockGetModMenu, mockInitialize, mockModRoutes } = vi.hoisted(() => ({
  mockGetModMenu: vi.fn(),
  mockInitialize: vi.fn(),
  mockModRoutes: [] as unknown[],
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    getModMenu: mockGetModMenu,
    initialize: mockInitialize,
    modsForUi: mockModsForUiRef,
    modRoutes: mockModRoutes,
  }),
}))

vi.mock('pinia', async (importOriginal) => {
  const actual = await importOriginal<typeof import('pinia')>()
  return {
    ...actual,
    storeToRefs: vi.fn(() => ({
      modsForUi: mockModsForUiRef,
    })),
  }
})

import { useModRoutes } from './useModRoutes'

describe('useModRoutes', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockGetModMenu.mockReset()
    mockInitialize.mockReset()
    mockGetModMenu.mockReturnValue([])
    mockInitialize.mockResolvedValue(undefined)
    mockModsForUiRef.value = []
  })

  it('returns modMenuItems computed ref', () => {
    mockGetModMenu.mockReturnValue([])
    const { modMenuItems } = useModRoutes()
    expect(modMenuItems).toBeDefined()
    expect(modMenuItems.value).toEqual([])
  })

  it('maps menu items with mod- prefix when id does not start with mod-', () => {
    mockGetModMenu.mockReturnValue([
      { id: 'my-mod', label: 'My Mod', icon: 'fa-icon', modId: 'mod-1', path: '/mod-1' },
    ])
    const { modMenuItems } = useModRoutes()
    expect(modMenuItems.value).toHaveLength(1)
    expect(modMenuItems.value[0].key).toBe('mod-my-mod')
    expect(modMenuItems.value[0].name).toBe('My Mod')
    expect(modMenuItems.value[0].iconClass).toBe('fa-icon')
    expect(modMenuItems.value[0].modId).toBe('mod-1')
    expect(modMenuItems.value[0].path).toBe('/mod-1')
  })

  it('does not add mod- prefix when id already starts with mod-', () => {
    mockGetModMenu.mockReturnValue([
      { id: 'mod-existing', label: 'Existing', icon: '', modId: 'mod-2', path: '/mod-2' },
    ])
    const { modMenuItems } = useModRoutes()
    expect(modMenuItems.value[0].key).toBe('mod-existing')
  })

  it('uses default icon fa-plug when icon is empty', () => {
    mockGetModMenu.mockReturnValue([
      { id: 'no-icon', label: 'No Icon', icon: '', modId: 'mod-3', path: '/mod-3' },
    ])
    const { modMenuItems } = useModRoutes()
    expect(modMenuItems.value[0].iconClass).toBe('fa-plug')
  })

  it('uses default icon fa-plug when icon is undefined', () => {
    mockGetModMenu.mockReturnValue([
      { id: 'no-icon', label: 'No Icon', modId: 'mod-4', path: '/mod-4' },
    ])
    const { modMenuItems } = useModRoutes()
    expect(modMenuItems.value[0].iconClass).toBe('fa-plug')
  })

  it('trims whitespace in menu id', () => {
    mockGetModMenu.mockReturnValue([
      { id: '  spaced  ', label: 'Spaced', modId: 'mod-5', path: '/mod-5' },
    ])
    const { modMenuItems } = useModRoutes()
    expect(modMenuItems.value[0].key).toBe('mod-spaced')
  })

  it('handles empty string id', () => {
    mockGetModMenu.mockReturnValue([
      { id: '', label: 'Empty', modId: 'mod-6', path: '/mod-6' },
    ])
    const { modMenuItems } = useModRoutes()
    expect(modMenuItems.value[0].key).toBe('mod-')
  })

  it('returns initializeMods function that calls store.initialize', async () => {
    const { initializeMods } = useModRoutes()
    await initializeMods()
    expect(mockInitialize).toHaveBeenCalledTimes(1)
  })

  it('returns mods ref from store', () => {
    const { mods } = useModRoutes()
    expect(mods).toBeDefined()
  })

  it('returns modRoutes from store', () => {
    const { modRoutes } = useModRoutes()
    expect(modRoutes).toBeDefined()
  })

  it('maps multiple menu items', () => {
    mockGetModMenu.mockReturnValue([
      { id: 'a', label: 'A', icon: 'fa-a', modId: 'mod-a', path: '/a' },
      { id: 'mod-b', label: 'B', icon: 'fa-b', modId: 'mod-b', path: '/b' },
      { id: 'c', label: 'C', modId: 'mod-c', path: '/c' },
    ])
    const { modMenuItems } = useModRoutes()
    expect(modMenuItems.value).toHaveLength(3)
    expect(modMenuItems.value[0].key).toBe('mod-a')
    expect(modMenuItems.value[1].key).toBe('mod-b')
    expect(modMenuItems.value[2].key).toBe('mod-c')
  })
})

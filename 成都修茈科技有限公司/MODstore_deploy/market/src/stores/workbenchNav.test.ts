import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

vi.mock('../composables/useBreakpoint', () => ({
  useBreakpoint: () => ({ isMobile: ref(false) }),
}))

import { useWorkbenchNavStore } from './workbenchNav'

describe('useWorkbenchNavStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initializes with default state', () => {
    const store = useWorkbenchNavStore()
    expect(store.activeGear).toBe('make')
    expect(store.gearScenes).toHaveLength(3)
    expect(store.gearScenes.map((g) => g.key)).toEqual(['direct', 'make', 'voice'])
    expect(store.sidebarCollapsed).toBe(false)
    expect(store.sidebarMobileOpen).toBe(false)
    expect(store.gearNavHardLocked).toBe(false)
  })

  it('setGear updates activeGear to a valid key', () => {
    const store = useWorkbenchNavStore()
    store.setGear('direct')
    expect(store.activeGear).toBe('direct')
    store.setGear('voice')
    expect(store.activeGear).toBe('voice')
  })

  it('setGear is a no-op when gearNavHardLocked is true', () => {
    const store = useWorkbenchNavStore()
    store.lockGearNav()
    expect(store.gearNavHardLocked).toBe(true)
    store.setGear('direct')
    expect(store.activeGear).toBe('make')
  })

  it('lockGearNav and unlockGearNav toggle the hard lock', () => {
    const store = useWorkbenchNavStore()
    store.lockGearNav()
    expect(store.gearNavHardLocked).toBe(true)
    store.unlockGearNav()
    expect(store.gearNavHardLocked).toBe(false)
    store.setGear('direct')
    expect(store.activeGear).toBe('direct')
  })

  it('toggleSidebar flips sidebarCollapsed', () => {
    const store = useWorkbenchNavStore()
    expect(store.sidebarCollapsed).toBe(false)
    store.toggleSidebar()
    expect(store.sidebarCollapsed).toBe(true)
    store.toggleSidebar()
    expect(store.sidebarCollapsed).toBe(false)
  })

  it('setSidebarCollapsed sets an explicit value', () => {
    const store = useWorkbenchNavStore()
    store.setSidebarCollapsed(true)
    expect(store.sidebarCollapsed).toBe(true)
    store.setSidebarCollapsed(false)
    expect(store.sidebarCollapsed).toBe(false)
  })

  it('toggleMobileSidebar flips sidebarMobileOpen', () => {
    const store = useWorkbenchNavStore()
    expect(store.sidebarMobileOpen).toBe(false)
    store.toggleMobileSidebar()
    expect(store.sidebarMobileOpen).toBe(true)
    store.toggleMobileSidebar()
    expect(store.sidebarMobileOpen).toBe(false)
  })

  it('gearIndex returns the index of the active gear', () => {
    const store = useWorkbenchNavStore()
    expect(store.gearIndex).toBe(1)
    store.setGear('direct')
    expect(store.gearIndex).toBe(0)
    store.setGear('voice')
    expect(store.gearIndex).toBe(2)
  })

  it('activeGearScene returns the active scene object', () => {
    const store = useWorkbenchNavStore()
    expect(store.activeGearScene.key).toBe('make')
    expect(store.activeGearScene.label).toBe('做')
    store.setGear('direct')
    expect(store.activeGearScene.key).toBe('direct')
    expect(store.activeGearScene.num).toBe('1')
  })

  it('activeGearScene falls back to first scene when key not found', () => {
    const store = useWorkbenchNavStore()
    store.$patch({ activeGear: 'nonexistent' })
    expect(store.activeGearScene).toEqual(store.gearScenes[0])
  })
})

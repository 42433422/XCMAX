import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useBreakpoint } from '../composables/useBreakpoint'

export interface GearScene {
  key: string
  num: string
  label: string
}

export const useWorkbenchNavStore = defineStore('workbenchNav', () => {
  const { isMobile } = useBreakpoint()
  const activeGear = ref<string>('make')
  const gearScenes = ref<GearScene[]>([
    { key: 'direct', num: '1', label: '聊' },
    { key: 'make', num: '2', label: '做' },
    { key: 'voice', num: '3', label: '说' },
  ])
  const sidebarCollapsed = ref(false)
  const sidebarMobileOpen = ref(false)
  const gearNavHardLocked = ref(false)

  const gearIndex = computed(() => gearScenes.value.findIndex((g) => g.key === activeGear.value))
  const activeGearScene = computed(() => gearScenes.value.find((g) => g.key === activeGear.value) ?? gearScenes.value[0])

  function setGear(key: string) {
    if (gearNavHardLocked.value) return
    activeGear.value = key
  }

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function setSidebarCollapsed(val: boolean) {
    sidebarCollapsed.value = val
  }

  function toggleMobileSidebar() {
    sidebarMobileOpen.value = !sidebarMobileOpen.value
  }

  function lockGearNav() {
    gearNavHardLocked.value = true
  }

  function unlockGearNav() {
    gearNavHardLocked.value = false
  }

  return {
    isMobile,
    activeGear,
    gearScenes,
    sidebarCollapsed,
    sidebarMobileOpen,
    gearNavHardLocked,
    gearIndex,
    activeGearScene,
    setGear,
    toggleSidebar,
    setSidebarCollapsed,
    toggleMobileSidebar,
    lockGearNav,
    unlockGearNav,
  }
})

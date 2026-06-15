import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/stores/industry', () => ({
  useIndustryStore: () => ({ currentIndustryId: ref('generic') }),
}))
vi.mock('@/stores/sidebarLayout', () => ({
  useSidebarLayoutStore: () => ({
    collapsed: ref(false),
    applyOrder: (items: unknown[]) => items,
  }),
}))
vi.mock('@/stores/mods', async () => {
  const { ref } = await import('vue')
  return {
    useModsStore: () => {
      const mods = ref([{ id: 'mod-1', name: 'Mod1' }])
      return {
        mods,
        modsForUi: mods,
        activeModId: ref('mod-1'),
        clientModsUiOff: ref(false),
        modRoutes: ref([]),
      }
    },
  }
})
vi.mock('@/stores/accountProfile', () => ({
  useAccountProfileStore: () => ({
    isLoggedIn: true,
    isAdminAccount: false,
    accountKind: 'personal',
    marketIsAdmin: false,
    marketIsEnterprise: false,
  }),
}))
vi.mock('@/composables/useModRoutes', async () => {
  const { ref } = await import('vue')
  return {
    useModRoutes: () => ({
      modMenuItems: ref([{ key: 'mod-chat', name: '对话', path: '/chat', modId: 'mod-1' }]),
    }),
  }
})
vi.mock('@/constants/platformShellMode', () => ({
  isPlatformShellModeEnabled: () => false,
  resolvePlatformShellMenuKeys: () => [],
  shouldExposeIndustrySidebar: () => false,
}))
vi.mock('@/constants/genericModPack', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/constants/genericModPack')>()
  return { ...actual, isClientErpSidebarContext: () => false }
})
vi.mock('@/constants/customerServiceNav', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/constants/customerServiceNav')>()
  return { ...actual, isCustomerServiceNavVisible: () => true }
})
vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => false,
}))
vi.mock('@/utils/roleMenuProfile', () => ({
  buildRoleMenuProfile: () => ({
    role: 'personal',
    canSeeAdminMenus: false,
    canSeeSettings: true,
  }),
  canShowCoreMenuKey: () => true,
}))
vi.mock('@/constants/attendanceIndustryMod', () => ({
  shouldHideAttendanceModSidebarMenu: () => false,
  ADMIN_OPERATOR_ATTENDANCE_MOD_IDS: new Set<string>(),
  ADMIN_OPERATOR_HIDDEN_MOD_IDS: new Set<string>(),
}))

import { useVisibleNavItems } from './useVisibleNavItems'

describe('useVisibleNavItems deep', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('returns visible nav items array', () => {
    const { visibleNavItems } = useVisibleNavItems()
    expect(Array.isArray(visibleNavItems.value)).toBe(true)
    expect(visibleNavItems.value.length).toBeGreaterThan(0)
  })

  it('each item has routeName and source', () => {
    const { visibleNavItems } = useVisibleNavItems()
    for (const item of visibleNavItems.value) {
      expect(item.key).toBeTruthy()
      expect(item.routeName).toBeTruthy()
      expect(item.source).toBeTruthy()
    }
  })
})

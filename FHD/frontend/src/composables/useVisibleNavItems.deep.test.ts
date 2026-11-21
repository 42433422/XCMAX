import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const account = vi.hoisted(() => ({ admin: false, enterprise: false, userRole: '' }))
// Match adminConsole.vite.config.js: test the real admin module, not the host stub.
vi.mock('@/constants/adminOperatorNav', () => import('../../../admin-console/src/constants/adminOperatorNav'))

vi.mock('@/stores/industry', () => ({
  useIndustryStore: () => ({ currentIndustryId: account.admin ? '管理端' : '通用' }),
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
    isAdminAccount: account.admin,
    accountKind: account.admin ? 'admin' : account.enterprise ? 'enterprise' : 'personal',
    marketIsAdmin: account.admin,
    marketIsEnterprise: account.enterprise,
    userRole: account.userRole,
    permissions: [],
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
  isAdminConsoleSpa: () => account.admin,
}))

import { useVisibleNavItems } from './useVisibleNavItems'

describe('useVisibleNavItems deep', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    Object.assign(account, { admin: false, enterprise: false, userRole: '' })
  })

  it('returns visible nav items array', () => {
    const { visibleNavItems } = useVisibleNavItems()
    expect(Array.isArray(visibleNavItems.value)).toBe(true)
    expect(visibleNavItems.value.length).toBeGreaterThan(0)
  })

  it('keeps 智能对话 visible and pinned first', () => {
    const { visibleNavItems } = useVisibleNavItems()
    expect(visibleNavItems.value[0]).toMatchObject({
      key: 'chat',
      name: '智能对话',
      routeName: 'chat',
    })
  })

  it('each item has routeName and source', () => {
    const { visibleNavItems } = useVisibleNavItems()
    for (const item of visibleNavItems.value) {
      expect(item.key).toBeTruthy()
      expect(item.routeName).toBeTruthy()
      expect(item.source).toBeTruthy()
    }
  })

  it.each(['admin', 'enterprise'])('keeps all three employee surfaces after %s menu filtering', (surface) => {
    account.admin = surface === 'admin'
    account.enterprise = surface === 'enterprise'
    const { visibleNavItems } = useVisibleNavItems()
    const children = visibleNavItems.value.filter(item => item.parentKey === 'employee-workflow')
    expect(children.map(({ routeName, name }) => ({ routeName, name }))).toEqual([
      { routeName: 'employee-workbench', name: '员工工作台' },
      { routeName: 'workflow-employee-space', name: '员工工作空间' },
      { routeName: 'workflow-employee-stitch-full', name: '员工图谱' },
    ])
  })

  it('preserves tenant-member permission filtering for employee surfaces', () => {
    Object.assign(account, { enterprise: true, userRole: 'tenant:3:member' })
    const { visibleNavItems } = useVisibleNavItems()
    expect(visibleNavItems.value.some(item => item.key === 'employee-workflow' || item.parentKey === 'employee-workflow')).toBe(false)
  })
})

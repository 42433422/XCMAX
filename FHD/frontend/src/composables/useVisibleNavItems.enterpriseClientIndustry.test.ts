import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const mockFlags = vi.hoisted(() => ({
  clientErpSidebarContext: true,
  exposeIndustrySidebar: true,
}))

vi.mock('@/constants/platformShellMode', () => ({
  isPlatformShellModeEnabled: () => false,
  shouldExposeIndustrySidebar: () => mockFlags.exposeIndustrySidebar,
  resolvePlatformShellMenuKeys: () => new Set<string>(),
}))

vi.mock('@/constants/genericModPack', () => ({
  isClientErpSidebarContext: () => mockFlags.clientErpSidebarContext,
  keepHostNavKeyVisibleWhenModSidebarFacetSuppressed: () => false,
  normalizeModSidebarNavKey: (key: string) => String(key || '').replace(/^mod-mod-/, 'mod-'),
  shouldHideAttendanceModSidebarMenu: () => false,
  shouldSuppressClientErpModMenuId: (menuId: string) =>
    String(menuId || '').startsWith('mod-erp-'),
  isHostBridgeModId: (modId: string) => String(modId || '').startsWith('xcagi-'),
  MOD_MENU_ID_TO_HOST_NAV_KEY: {
    'mod-erp-products': 'products',
    'mod-erp-customers': 'customers',
    'mod-erp-data-sources': 'data-sources',
  },
}))

vi.mock('@/stores/industry', () => ({
  useIndustryStore: () => ({ currentIndustryId: '考勤' }),
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
      const mods = ref([
        {
          id: 'taiyangniao-pro',
          name: '太阳鸟 PRO',
          menu_overrides: [
            { key: 'products', label: '人员管理' },
            { key: 'customers', label: '部门管理' },
          ],
        },
        {
          id: 'xcagi-erp-domain-bridge',
          name: 'ERP 门面',
          menu_overrides: [
            { key: 'products', hidden: true },
            { key: 'customers', hidden: true },
          ],
        },
      ])
      return {
        mods,
        modsForUi: mods,
        activeModId: ref('taiyangniao-pro'),
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
    accountKind: 'enterprise',
    marketIsAdmin: false,
    marketIsEnterprise: true,
  }),
}))

vi.mock('@/composables/useModRoutes', async () => {
  const { ref } = await import('vue')
  return {
    useModRoutes: () => ({
      modMenuItems: ref([
        {
          key: 'mod-erp-data-sources',
          name: '数据来源',
          path: '/mod/xcagi-erp-domain-bridge/data-sources',
          modId: 'xcagi-erp-domain-bridge',
        },
      ]),
    }),
  }
})

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => false,
}))

vi.mock('@/utils/roleMenuProfile', () => ({
  buildRoleMenuProfile: () => ({
    role: 'enterprise-user',
    canSeeAdminMenus: false,
    canSeeSettings: true,
  }),
  canShowCoreMenuKey: () => true,
}))

import { useVisibleNavItems } from './useVisibleNavItems'

describe('useVisibleNavItems · 企业完整包客户行业侧栏', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    mockFlags.clientErpSidebarContext = true
    mockFlags.exposeIndustrySidebar = true
  })

  it('非平台壳模式下选中太阳鸟也注入宿主业务卡片', () => {
    const { visibleNavItems } = useVisibleNavItems()
    const keys = visibleNavItems.value.map((i) => i.key)

    expect(keys).toContain('products')
    expect(keys).toContain('customers')
    expect(keys).toContain('data-sources')
    expect(keys).not.toContain('mod-erp-data-sources')
    expect(visibleNavItems.value.find((i) => i.key === 'products')?.name).toBe('人员管理')
    expect(visibleNavItems.value.find((i) => i.key === 'customers')?.name).toBe('部门管理')
  })

  it('账号定制已开放侧栏时不依赖主 ERP 上下文', () => {
    mockFlags.clientErpSidebarContext = false

    const { visibleNavItems } = useVisibleNavItems()
    const keys = visibleNavItems.value.map((i) => i.key)

    expect(keys).toContain('products')
    expect(keys).toContain('customers')
    expect(keys).toContain('data-sources')
    expect(visibleNavItems.value.find((i) => i.key === 'products')?.name).toBe('人员管理')
  })

  it('完整企业版即使尚未确认 host pack 也显示 ERP 业务入口', () => {
    mockFlags.clientErpSidebarContext = false
    mockFlags.exposeIndustrySidebar = false

    const { visibleNavItems } = useVisibleNavItems()
    const keys = visibleNavItems.value.map((i) => i.key)

    expect(keys).toContain('products')
    expect(keys).toContain('customers')
    expect(keys).toContain('orders')
    expect(keys).toContain('inventory')
    expect(keys).toContain('approval-hub')
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

// 平台壳模式开启；其余 platformShellMode 行为保留真实实现（含 resolvePlatformShellMenuKeys / shouldExposeIndustrySidebar）
vi.mock('@/constants/platformShellMode', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/constants/platformShellMode')>()
  return { ...actual, isPlatformShellModeEnabled: () => true }
})

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
        { id: 'attendance-industry', name: '考勤行业包' },
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
        activeModId: ref(null),
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
          key: 'mod-erp-products',
          name: '业务对象',
          path: '/mod/xcagi-erp-domain-bridge/products',
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

import { markHostPackAcknowledged } from '@/constants/productFlow'
import { useVisibleNavItems } from './useVisibleNavItems'

describe('useVisibleNavItems · 平台壳第三步完成后长出行业菜单', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('未完成补基础线（host ack=false）：主导航不长出 ERP 业务项', () => {
    const { visibleNavItems } = useVisibleNavItems()
    const keys = visibleNavItems.value.map((i) => i.key)
    expect(keys).not.toContain('products')
    expect(keys).not.toContain('customers')
    expect(keys).toContain('chat')
  })

  it('完成补基础线后：长出考勤业务项且 label 本地化为人员/部门管理', () => {
    markHostPackAcknowledged()
    const { visibleNavItems } = useVisibleNavItems()
    const keys = visibleNavItems.value.map((i) => i.key)
    expect(keys).toContain('products')
    expect(keys).toContain('customers')
    expect(keys).toContain('orders')

    const products = visibleNavItems.value.find((i) => i.key === 'products')
    const customers = visibleNavItems.value.find((i) => i.key === 'customers')
    expect(products?.name).toBe('人员管理')
    expect(customers?.name).toBe('部门管理')

    // erp-domain-bridge 的同名 mod 入口被合并去重，products 槽位只出现一次
    const productSlots = visibleNavItems.value.filter(
      (i) => i.key === 'products' || i.key === 'mod-erp-products',
    )
    expect(productSlots.length).toBe(1)
  })
})

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { Router } from 'vue-router'
import { getSidebarNavigationGeneration, navigateFromSidebarKey, resetSidebarNavigationForTests } from '@/utils/sidebarNavigation'

vi.mock('@/utils/desktopShell', () => ({
  isDesktopShell: () => true,
}))

vi.mock('@/constants/platformShellMode', () => ({
  isEnterpriseProductSkuBuild: () => true,
  isPlatformShellModeEnabled: () => false,
  INDUSTRY_DELIVERY_ERP_MENU_KEYS: ['print', 'products', 'customers'],
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => false,
}))

vi.mock('@/utils/hostBusinessPageRedirect', () => ({
  resolveHostBusinessPageRedirect: vi.fn(() => null),
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    getModMenu: () => [],
  }),
}))

function makeRouter(hasRoutes: string[] = ['print', 'workflow-employee-space', 'customers']) {
  const push = vi.fn(async () => undefined)
  return {
    push,
    hasRoute: (name: string) => hasRoutes.includes(name),
    resolve: (path: string) => ({
      matched: hasRoutes.some((name) => path.includes(name)) ? [{}] : [],
    }),
  } as unknown as Router
}

describe('sidebarNavigation', () => {
  beforeEach(() => {
    resetSidebarNavigationForTests()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('employee-workflow 映射到 workflow-employee-space 宿主路由', async () => {
    const router = makeRouter()
    await navigateFromSidebarKey(router, 'employee-workflow')
    expect(router.push).toHaveBeenCalledWith({ name: 'workflow-employee-space' })
  })

  it('print 在 Enterprise 桌面优先走宿主 print 路由', async () => {
    const router = makeRouter()
    await navigateFromSidebarKey(router, 'print')
    expect(router.push).toHaveBeenCalledWith({ name: 'print' })
  })

  it('连点侧栏时只执行最后一次导航', async () => {
    const router = makeRouter()
    void navigateFromSidebarKey(router, 'customers')
    await navigateFromSidebarKey(router, 'employee-workflow')

    expect(getSidebarNavigationGeneration()).toBe(2)
    expect(router.push).toHaveBeenCalledTimes(1)
    expect(router.push).toHaveBeenCalledWith({ name: 'workflow-employee-space' })
  })
})

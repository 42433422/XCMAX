import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { Router } from 'vue-router'
import {
  getSidebarNavigationGeneration,
  getQueuedSidebarViewKey,
  isSidebarNavigationPending,
  navigateFromSidebarKey,
  resetSidebarNavigationForTests,
} from '@/utils/sidebarNavigation'

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

  it('employee-workflow maps to workflow-employee-space host route', async () => {
    const router = makeRouter()
    await navigateFromSidebarKey(router, 'employee-workflow')
    expect(router.push).toHaveBeenCalledWith({ name: 'workflow-employee-space' })
  })

  it('print prefers host print route on Enterprise desktop', async () => {
    const router = makeRouter()
    await navigateFromSidebarKey(router, 'print')
    expect(router.push).toHaveBeenCalledWith({ name: 'print' })
  })

  it('coalesces rapid sidebar clicks to the last target', async () => {
    const router = makeRouter()
    void navigateFromSidebarKey(router, 'customers')
    await navigateFromSidebarKey(router, 'employee-workflow')

    expect(getSidebarNavigationGeneration()).toBe(2)
    expect(router.push).toHaveBeenCalledTimes(1)
    expect(router.push).toHaveBeenCalledWith({ name: 'workflow-employee-space' })
  })

  it('fast second click supersedes a slow first navigation', async () => {
    const push = vi.fn(async () => {
      await new Promise((r) => setTimeout(r, 30))
    })
    const router = {
      push,
      hasRoute: (name: string) => ['customers', 'print'].includes(name),
      resolve: () => ({ matched: [{}] }),
    } as unknown as Router

    const first = navigateFromSidebarKey(router, 'customers')
    const second = navigateFromSidebarKey(router, 'print')
    expect(getSidebarNavigationGeneration()).toBe(2)
    await Promise.all([first, second])
    expect(push).toHaveBeenCalled()
    expect(push.mock.calls.at(-1)?.[0]).toEqual({ name: 'print' })
    expect(getQueuedSidebarViewKey()).toBeNull()
    expect(isSidebarNavigationPending()).toBe(false)
  })
})

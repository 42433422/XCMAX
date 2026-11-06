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

function makeRouter(hasRoutes: string[] = ['print', 'workflow-employee-space', 'customers'], currentName = 'chat') {
  const currentRoute = { value: { name: currentName, path: `/${currentName}` } }
  const push = vi.fn(async (loc: { name?: string; path?: string } | string) => {
    if (typeof loc === 'string') {
      currentRoute.value = { name: loc.replace(/^\//, ''), path: loc }
    } else if (loc && typeof loc === 'object') {
      const name = String(loc.name || '')
      currentRoute.value = { name, path: loc.path || `/${name}` }
    }
  })
  return {
    push,
    currentRoute,
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

  it('opens customers and products on their own host routes', async () => {
    const router = makeRouter(['print', 'products', 'customers', 'workflow-employee-space'])
    await navigateFromSidebarKey(router, 'customers')
    expect(router.push).toHaveBeenCalledWith({ name: 'customers' })
    await navigateFromSidebarKey(router, 'products')
    expect(router.push).toHaveBeenLastCalledWith({ name: 'products' })
  })

  it('coalesces rapid sidebar clicks to the last target', async () => {
    const router = makeRouter()
    void navigateFromSidebarKey(router, 'customers')
    await navigateFromSidebarKey(router, 'employee-workflow')

    expect(getSidebarNavigationGeneration()).toBe(2)
    expect(router.push).toHaveBeenCalledTimes(1)
    expect(router.push).toHaveBeenCalledWith({ name: 'workflow-employee-space' })
  })

  it('settles each coalesced call according to its own navigation', async () => {
    const router = makeRouter()
    const first = navigateFromSidebarKey(router, 'customers')
    const second = navigateFromSidebarKey(router, 'print')

    await expect(first).resolves.toBe(false)
    await expect(second).resolves.toBe(true)
    expect(isSidebarNavigationPending()).toBe(false)
  })

  it('uses the router belonging to the latest coalesced call', async () => {
    const firstRouter = makeRouter()
    const secondRouter = makeRouter()
    const first = navigateFromSidebarKey(firstRouter, 'customers')
    const second = navigateFromSidebarKey(secondRouter, 'print')

    await expect(first).resolves.toBe(false)
    await expect(second).resolves.toBe(true)
    expect(firstRouter.push).not.toHaveBeenCalled()
    expect(secondRouter.push).toHaveBeenCalledWith({ name: 'print' })
  })

  it('does not let a superseded call inherit the latest push error', async () => {
    const router = makeRouter()
    const error = new Error('latest failed')
    vi.mocked(router.push).mockRejectedValueOnce(error)
    const first = navigateFromSidebarKey(router, 'customers')
    const second = navigateFromSidebarKey(router, 'print')
    const results = await Promise.allSettled([first, second])

    expect(results).toEqual([{ status: 'fulfilled', value: false }, { status: 'rejected', reason: error }])
    expect(isSidebarNavigationPending()).toBe(false)
  })

  it('fast second click supersedes a slow first navigation', async () => {
    const currentRoute = { value: { name: 'chat', path: '/chat' } }
    const push = vi.fn(async (loc: { name?: string }) => {
      await new Promise((r) => setTimeout(r, 30))
      if (loc?.name) currentRoute.value = { name: String(loc.name), path: `/${loc.name}` }
    })
    const router = {
      push,
      currentRoute,
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

  it('propagates a current push failure and permits a retry', async () => {
    const router = makeRouter()
    const error = new Error('Failed to fetch dynamically imported module')
    vi.mocked(router.push).mockRejectedValueOnce(error)
    await expect(navigateFromSidebarKey(router, 'print')).rejects.toBe(error)
    expect(isSidebarNavigationPending()).toBe(false)
    await expect(navigateFromSidebarKey(router, 'print')).resolves.toBe(true)
  })

  it('starts the next target immediately and consumes a superseded push rejection', async () => {
    let rejectFirst: ((error: Error) => void) | undefined
    let pushes = 0
    const currentRoute = { value: { name: 'chat', path: '/chat' } }
    const push = vi.fn((loc: { name?: string }) => {
      pushes += 1
      if (pushes === 1) {
        return new Promise<void>((_, reject) => {
          rejectFirst = reject
        })
      }
      if (loc?.name) currentRoute.value = { name: String(loc.name), path: `/${loc.name}` }
      return Promise.resolve()
    })
    const router = {
      push,
      currentRoute,
      hasRoute: (name: string) => ['customers', 'print'].includes(name),
      resolve: () => ({ matched: [{}] }),
    } as unknown as Router
    const first = navigateFromSidebarKey(router, 'customers')
    await vi.waitFor(() => expect(push).toHaveBeenCalledTimes(1))
    const second = navigateFromSidebarKey(router, 'print')
    await vi.waitFor(() => expect(push).toHaveBeenCalledTimes(2))
    expect(push.mock.calls.at(-1)?.[0]).toEqual({ name: 'print' })
    await Promise.all([first, second])
    rejectFirst?.(new Error('Superseded chunk load failed'))
    await Promise.resolve()
    expect(isSidebarNavigationPending()).toBe(false)
  })
})

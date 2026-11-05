import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  createMemoryHistory,
  createRouter,
  type Router,
  type RouteRecordRaw,
} from 'vue-router'
import {
  beginAppNavIntent,
  classifyNavigationFailure,
  clearAppNavIntentIfCurrent,
  getActiveAppNavIntent,
  isAppNavIntentCurrent,
  pushWithAppNavIntent,
  resetAppNavigationForTests,
  routeMatchesTarget,
  shouldShowNavFailure,
} from '@/utils/appNavigation'
import {
  navigateFromSidebarKey,
  resetSidebarNavigationForTests,
  getQueuedSidebarViewKey,
  isSidebarNavigationPending,
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

vi.mock('@/router/registerModRoutes', () => ({
  registerAllModRoutesFromGlob: vi.fn(async () => undefined),
  registerModRoutes: vi.fn(async () => undefined),
}))

function makeAppRouter(extraGuards?: (router: Router) => void): Router {
  const routes: RouteRecordRaw[] = [
    { path: '/', name: 'chat', component: { template: '<div>chat</div>' } },
    { path: '/settings', name: 'settings', component: { template: '<div>settings</div>' } },
    { path: '/customers', name: 'customers', component: { template: '<div>customers</div>' } },
    { path: '/print', name: 'print', component: { template: '<div>print</div>' } },
    { path: '/products', name: 'products', component: { template: '<div>products</div>' } },
    {
      path: '/guarded',
      name: 'guarded',
      component: { template: '<div>guarded</div>' },
      beforeEnter: () => false,
    },
    {
      path: '/login',
      name: 'login',
      component: { template: '<div>login</div>' },
    },
    {
      path: '/auth-required',
      name: 'auth-required',
      component: { template: '<div>auth</div>' },
      beforeEnter: (_to, _from, next) => {
        next({ name: 'login' })
      },
    },
  ]
  const router = createRouter({
    history: createMemoryHistory(),
    routes,
  })
  extraGuards?.(router)
  return router
}

describe('appNavigation + real Vue Router', () => {
  beforeEach(() => {
    resetAppNavigationForTests()
    resetSidebarNavigationForTests()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('classifies NavigationFailure kinds without treating duplicated as error', async () => {
    const router = makeAppRouter()
    await router.push('/')
    await router.isReady()
    // duplicated
    try {
      await router.push({ name: 'chat' })
    } catch (error) {
      expect(classifyNavigationFailure(error)).toBe('duplicate')
      expect(shouldShowNavFailure('duplicate')).toBe(false)
    }
    // aborted by beforeEnter returning false
    try {
      await router.push({ name: 'guarded' })
    } catch (error) {
      expect(classifyNavigationFailure(error)).toBe('aborted')
      expect(shouldShowNavFailure('aborted')).toBe(true)
    }
  })

  it('treats already-on-target as duplicate success', async () => {
    const router = makeAppRouter()
    await router.push('/settings')
    await router.isReady()
    const intent = beginAppNavIntent('settings', 'test')
    const result = await pushWithAppNavIntent(router, { name: 'settings' }, intent, {
      match: { name: 'settings', key: 'settings' },
    })
    expect(result.status).toBe('duplicate')
    expect(routeMatchesTarget(router, { name: 'settings' })).toBe(true)
  })

  it('reports aborted when a guard rejects navigation', async () => {
    const router = makeAppRouter()
    await router.push('/')
    await router.isReady()
    const intent = beginAppNavIntent('guarded', 'test')
    const result = await pushWithAppNavIntent(router, { name: 'guarded' }, intent, {
      match: { name: 'guarded', key: 'guarded' },
    })
    expect(result.status).toBe('aborted')
    expect(router.currentRoute.value.name).toBe('chat')
  })

  it('keeps arrived when guard redirects to a matching target alias path', async () => {
    const router = makeAppRouter()
    await router.push('/')
    await router.isReady()
    // Redirect from products to print but still match key via path include — use match on print
    router.beforeEach((to) => {
      if (to.name === 'products') return { name: 'print' }
    })
    const intent = beginAppNavIntent('print', 'test')
    const result = await pushWithAppNavIntent(router, { name: 'products' }, intent, {
      match: { name: 'print', key: 'print' },
    })
    // products push was redirected to print; with match on print we should arrive
    expect(['arrived', 'duplicate']).toContain(result.status)
    expect(router.currentRoute.value.name).toBe('print')
  })

  it('supersedes an in-flight push when a newer intent starts', async () => {
    const router = makeAppRouter()
    await router.push('/')
    await router.isReady()
    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    router.beforeEach(async (to) => {
      if (to.name === 'customers') await gate
    })
    const firstIntent = beginAppNavIntent('customers', 'sidebar')
    const first = pushWithAppNavIntent(router, { name: 'customers' }, firstIntent, {
      match: { name: 'customers', key: 'customers' },
    })
    await vi.waitFor(() => expect(getActiveAppNavIntent()?.targetKey).toBe('customers'))
    const secondIntent = beginAppNavIntent('settings', 'top-settings')
    expect(isAppNavIntentCurrent(firstIntent.id)).toBe(false)
    expect(isAppNavIntentCurrent(secondIntent.id)).toBe(true)
    const second = pushWithAppNavIntent(router, { name: 'settings' }, secondIntent, {
      match: { name: 'settings', key: 'settings' },
    })
    release()
    const [a, b] = await Promise.all([first, second])
    expect(a.status).toBe('superseded')
    expect(['arrived', 'duplicate']).toContain(b.status)
    expect(router.currentRoute.value.name).toBe('settings')
  })

  it('times out only the current wait without clearing a newer intent', async () => {
    vi.useFakeTimers()
    const router = makeAppRouter()
    await router.push('/')
    // useFakeTimers + router readiness: push sync
    let hangResolve!: () => void
    const hang = new Promise<void>((resolve) => {
      hangResolve = resolve
    })
    router.beforeEach(async (to) => {
      if (to.name === 'customers') await hang
    })
    const intent = beginAppNavIntent('customers', 'test')
    const pending = pushWithAppNavIntent(router, { name: 'customers' }, intent, {
      timeoutMs: 50,
      match: { name: 'customers', key: 'customers' },
    })
    await vi.advanceTimersByTimeAsync(60)
    const result = await pending
    expect(result.status).toBe('timeout')
    expect(shouldShowNavFailure(result.status)).toBe(true)
    // Newer intent remains owner
    const newer = beginAppNavIntent('settings', 'retry')
    expect(isAppNavIntentCurrent(newer.id)).toBe(true)
    clearAppNavIntentIfCurrent(intent.id) // must NOT clear newer
    expect(isAppNavIntentCurrent(newer.id)).toBe(true)
    hangResolve()
  })

  it('sidebar: old customers wait loses to newer settings (repro timeline)', async () => {
    const router = makeAppRouter()
    await router.push('/')
    await router.isReady()
    let releaseMod!: () => void
    const modGate = new Promise<void>((resolve) => {
      releaseMod = resolve
    })
    // Slow first navigation via beforeEach simulating Mod register delay
    let seenCustomers = 0
    router.beforeEach(async (to) => {
      if (to.name === 'customers') {
        seenCustomers += 1
        if (seenCustomers === 1) await modGate
      }
    })

    const first = navigateFromSidebarKey(router, 'customers', { source: 'sidebar' })
    await vi.waitFor(() => expect(getActiveAppNavIntent()?.targetKey).toBe('customers'))
    const second = navigateFromSidebarKey(router, 'settings', { source: 'top-settings' })
    await Promise.resolve()
    releaseMod()
    const [appliedOld, appliedNew] = await Promise.all([first, second])
    // Drain returns the last applied boolean for the shared drain promise —
    // both awaiters share the same drain result (last applied).
    expect(appliedOld).toBe(appliedNew)
    expect(router.currentRoute.value.name).toBe('settings')
    expect(getQueuedSidebarViewKey()).toBeNull()
    expect(isSidebarNavigationPending()).toBe(false)
  })

  it('sidebar: A→B→A ends on A and allows same-target retry after failure', async () => {
    const router = makeAppRouter()
    await router.push('/')
    await router.isReady()
    await navigateFromSidebarKey(router, 'customers')
    expect(router.currentRoute.value.name).toBe('customers')
    await navigateFromSidebarKey(router, 'print')
    expect(router.currentRoute.value.name).toBe('print')
    await navigateFromSidebarKey(router, 'customers')
    expect(router.currentRoute.value.name).toBe('customers')

    // Force an aborted failure then retry same target
    const boom = new Error('Failed to fetch dynamically imported module')
    const realPush = router.push.bind(router)
    const spy = vi.spyOn(router, 'push').mockImplementationOnce(async () => {
      throw boom
    })
    await expect(navigateFromSidebarKey(router, 'print')).rejects.toBe(boom)
    spy.mockRestore()
    // Restore push after one failure — retry same target must work
    await expect(navigateFromSidebarKey(router, 'print')).resolves.toBe(true)
    expect(router.currentRoute.value.name).toBe('print')
  })

  it('cross entry: ecosystem then sidebar keeps last user intent', async () => {
    const router = makeAppRouter()
    await router.push('/')
    await router.isReady()
    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    router.beforeEach(async (to) => {
      if (to.name === 'products') await gate
    })
    const eco = navigateFromSidebarKey(router, 'products', { source: 'ecosystem-card' })
    await vi.waitFor(() => expect(getActiveAppNavIntent()?.source).toBe('ecosystem-card'))
    const side = navigateFromSidebarKey(router, 'settings', { source: 'sidebar-or-quicknav' })
    release()
    await Promise.all([eco, side])
    expect(router.currentRoute.value.name).toBe('settings')
    expect(getActiveAppNavIntent() == null || getActiveAppNavIntent()?.targetKey === 'settings').toBe(true)
  })

  it('browser back/forward leaves URL on last history entry without stuck pending queue', async () => {
    const router = makeAppRouter()
    await router.push('/')
    await router.isReady()
    await navigateFromSidebarKey(router, 'customers')
    await navigateFromSidebarKey(router, 'settings')
    expect(router.currentRoute.value.name).toBe('settings')
    router.back()
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('customers'))
    expect(isSidebarNavigationPending()).toBe(false)
    router.forward()
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('settings'))
    expect(isSidebarNavigationPending()).toBe(false)
  })
})

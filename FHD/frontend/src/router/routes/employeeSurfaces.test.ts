import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useVisibleNavItems } from '@/composables/useVisibleNavItems'
import { ADMIN_HOST_ROUTE_RECORDS } from '../../../../admin-console/src/adminHostRoutes'

const account = vi.hoisted(() => ({
  accountKind: 'enterprise', isAdminAccount: false, marketIsAdmin: false, marketIsEnterprise: true,
  userRole: '', permissions: [] as string[], tenantId: null as number | null,
}))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => account }))
// Use the module that adminConsole.vite.config.js resolves in the real admin build.
vi.mock('@/constants/adminOperatorNav', () => import('../../../../admin-console/src/constants/adminOperatorNav'))
vi.mock('@/stores/industry', () => ({ useIndustryStore: () => ({ currentIndustryId: 'generic' }) }))
vi.mock('@/stores/sidebarLayout', () => ({ useSidebarLayoutStore: () => ({ applyOrder: (items: unknown[]) => items }) }))
vi.mock('@/stores/mods', async () => {
  const { ref } = await import('vue')
  return { useModsStore: () => {
    const mods = ref([])
    return { mods, modsForUi: mods, activeModId: ref('') }
  } }
})
vi.mock('@/composables/useModRoutes', async () => {
  const { ref } = await import('vue')
  return { useModRoutes: () => ({ modMenuItems: ref([]) }) }
})

beforeEach(() => {
  vi.resetModules()
  localStorage.clear()
  window.history.replaceState({}, '', '/')
  setActivePinia(createPinia())
  Object.assign(account, { accountKind: 'enterprise', isAdminAccount: false, marketIsAdmin: false,
    marketIsEnterprise: true, userRole: '', permissions: [], tenantId: null })
})
afterEach(() => vi.unstubAllEnvs())

const surfaces = ['employee-workbench', 'workflow-employee-space', 'workflow-employee-stitch-full']

describe('employee surfaces stay independently reachable', () => {
  it.each(['', '1'])('navigates each visible employee surface on client %s', async (admin) => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', admin)
    if (admin) Object.assign(account, { accountKind: 'admin', isAdminAccount: true, marketIsAdmin: true, marketIsEnterprise: false })
    const entries = useVisibleNavItems().visibleNavItems.value.filter(item => item.parentKey === 'employee-workflow')
    expect(entries.map(item => item.routeName)).toEqual(surfaces)
    const { SHELL_ROUTES } = await import('./shell')
    const routes = [...SHELL_ROUTES, ...(admin ? ADMIN_HOST_ROUTE_RECORDS : [])]
      .filter(route => surfaces.includes(String(route.name)) || route.name === 'duty-roster-graph')
      .map(route => route.redirect ? route : { ...route, component: { template: '<div />' } })
    const router = createRouter({ history: createMemoryHistory(), routes })
    for (const entry of entries) {
      await router.push({ name: entry.routeName })
      const target = admin && entry.key === 'workflow-employee-stitch-full' ? 'duty-roster-graph' : entry.key
      expect(router.currentRoute.value.name).toBe(target)
      if (target === 'duty-roster-graph') expect(router.currentRoute.value.meta.requiresAdminAccount).toBe(true)
    }
    expect(router.hasRoute('duty-roster-graph')).toBe(Boolean(admin))
  })

  it('keeps ungranted employee entries hidden for invited tenant members', () => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
    Object.assign(account, { userRole: 'tenant:7:member', tenantId: 7, permissions: ['elt.read'] })
    const keys = useVisibleNavItems().visibleNavItems.value.map(item => item.key)
    expect(keys).toContain('business-docking')
    expect(keys).not.toContain('employee-workflow')
    for (const key of surfaces) expect(keys).not.toContain(key)
  })

  it('keeps sandbox employee navigation backed by registered routes', async () => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
    window.history.replaceState({}, '', '/?sandbox')
    const { SHELL_ROUTES } = await import('./shell')
    const { resolveInitialRoutes } = await import('../initialRouteSelection')
    const names = resolveInitialRoutes(SHELL_ROUTES).map(route => route.name)
    const entries = useVisibleNavItems().visibleNavItems.value.filter(item => item.parentKey === 'employee-workflow')
    expect(entries).toHaveLength(3)
    for (const entry of entries) expect(names).toContain(entry.routeName)
  })
})


describe('employee navigation contracts', () => {
  it('keeps workbench, workspace and graph as distinct navigation entries', async () => {
    const { CORE_MENU_ITEMS_BASE } = await import('@/constants/coreMenuCatalog')
    const parent = CORE_MENU_ITEMS_BASE.find((item) => item.key === 'employee-workflow')
    expect(parent?.children?.map((child) => child.key)).toEqual([
      'employee-workbench', 'workflow-employee-space', 'workflow-employee-stitch-full',
    ])
  })

  it('binds the task workbench and desk workspace to separate components', async () => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
    const { SHELL_ROUTES } = await import('./shell')
    const workbench = SHELL_ROUTES.find((route) => route.name === 'employee-workbench')
    const workspace = SHELL_ROUTES.find((route) => route.name === 'workflow-employee-space')
    const graph = SHELL_ROUTES.find((route) => route.name === 'workflow-employee-stitch-full')
    expect(workbench?.path).toBe('/employee-workbench')
    expect(workspace?.path).toBe('/workflow-employee-space')
    expect(workbench?.component).not.toBe(workspace?.component)
    expect(graph?.path).toBe('/workflow-employee-space/stitch-full')
  })
})

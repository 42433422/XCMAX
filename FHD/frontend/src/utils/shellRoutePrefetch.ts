import type { Router } from 'vue-router'
import { CORE_NAV_KEYS, INDUSTRY_DELIVERY_CORE_ITEMS, flattenNavKeys } from '@/constants/coreMenuCatalog'
import { INDUSTRY_DELIVERY_ROUTE_NAMES } from '@/constants/platformShellMode'
import { resolveNavRouteName } from '@/constants/navRouteAliases'
import { prefetchRouteChunks } from '@/utils/routePrefetch'

const SHELL_ROUTE_NAMES = new Set<string>([
  ...CORE_NAV_KEYS,
  ...flattenNavKeys(INDUSTRY_DELIVERY_CORE_ITEMS),
  ...INDUSTRY_DELIVERY_ROUTE_NAMES,
])

const loaded = new Set<string>()
const scheduledRouters = new WeakSet<Router>()

function idle(task: () => void): void {
  const win = window as Window & { requestIdleCallback?: (cb: () => void, options?: { timeout: number }) => number }
  if (typeof win.requestIdleCallback === 'function') win.requestIdleCallback(task, { timeout: 1500 })
  else window.setTimeout(task, 200)
}

function loaderFor(router: Router, name: string): (() => Promise<unknown>) | null {
  const resolved = resolveNavRouteName(name) || name
  for (const candidate of [name, resolved]) {
    if (!candidate || loaded.has(candidate)) continue
    const route = router.getRoutes().find((item) => String(item.name || '') === candidate)
    const component = route?.components?.default
    if (typeof component === 'function') {
      return () => {
        loaded.add(candidate)
        return (component as () => Promise<unknown>)().catch((error: unknown) => {
          loaded.delete(candidate)
          throw error
        })
      }
    }
  }
  return null
}

/** Warm one sidebar destination immediately (hover / pointer). */
export function prefetchShellRoute(router: Router, name: string): void {
  const load = loaderFor(router, name)
  if (load) void load().catch(() => undefined)
}

/** Warm primary shell pages while the shell is idle so later switches do not wait on the chunk. */
export function prefetchShellRouteChunks(router: Router): void {
  if (scheduledRouters.has(router)) return
  const im = loaderFor(router, 'im')
  if (im) void im().catch(() => undefined)
  const rest = [...SHELL_ROUTE_NAMES].map((name) => loaderFor(router, name)).filter((job): job is () => Promise<unknown> => Boolean(job))
  if (!im && !rest.length) return
  scheduledRouters.add(router)
  // 信息 starts immediately. Other pages wait for idle, one at a time, so they do not
  // take the browser's connections from that first open.
  if (rest.length) void prefetchRouteChunks(rest, idle, 1)
}

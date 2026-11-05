import type { Router } from 'vue-router'
import {
  beginAppNavIntent,
  clearAppNavIntentIfCurrent,
  getAppNavIntentId,
  isAppNavIntentCurrent,
  pushWithAppNavIntent,
  resetAppNavigationForTests,
  shouldShowNavFailure,
  type AppNavOutcome,
} from '@/utils/appNavigation'
import { resolveNavRouteName } from '@/constants/navRouteAliases'
import { SIDEBAR_ROUTE_NAME_MAP } from '@/constants/sidebarRouteNameMap'
import { resolveHostBusinessPageRedirect } from '@/utils/hostBusinessPageRedirect'
import { customerServiceHostPathFromModPath } from '@/utils/customerServicePagePaths'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { isDesktopShell } from '@/utils/desktopShell'
import { isEnterpriseProductSkuBuild, isPlatformShellModeEnabled, INDUSTRY_DELIVERY_ERP_MENU_KEYS } from '@/constants/platformShellMode'
import { useModsStore } from '@/stores/mods'

export type SidebarModMenuItem = {
  key: string
  path?: string
}

export type NavigateFromSidebarOptions = {
  modMenuItems?: SidebarModMenuItem[]
  routeNameMap?: Record<string, string>
  getModRoutes?: () => unknown[] | undefined
}

let sidebarNavGeneration = 0
let queuedSidebarViewKey: string | null = null
let queuedSidebarOptions: NavigateFromSidebarOptions | null = null
let sidebarNavDrain: Promise<boolean> | null = null

export function resetSidebarNavigationForTests(): void {
  sidebarNavGeneration = 0
  queuedSidebarViewKey = null
  queuedSidebarOptions = null
  sidebarNavDrain = null
  resetAppNavigationForTests()
}

export function getSidebarNavigationGeneration(): number {
  return sidebarNavGeneration
}

function readModMenuItems(override?: SidebarModMenuItem[]): SidebarModMenuItem[] {
  if (override) return override
  try {
    const modsStore = useModsStore()
    return modsStore.getModMenu().map((item) => {
      const menuId = String(item.id || '').trim()
      const key = menuId.startsWith('mod-') ? menuId : `mod-${menuId}`
      return {
        key,
        path: item.path,
      }
    })
  } catch {
    return []
  }
}

function resolveLegacyRouteFromModPath(router: Router, modPath: string) {
  const pathOnly =
    String(modPath || '')
      .split('?')[0]
      ?.split('#')[0] || ''
  if (!pathOnly) return null
  if (pathOnly.includes('/approval-hub/workspace') && router.hasRoute('approval-workspace')) {
    return { name: 'approval-workspace' }
  }
  if (pathOnly.endsWith('/approval-hub') && router.hasRoute('approval-hub')) {
    return { name: 'approval-hub' }
  }
  const lastSeg = pathOnly.split('/').filter(Boolean).pop()
  if (lastSeg && router.hasRoute(lastSeg)) {
    return { name: lastSeg }
  }
  return null
}

/** Enterprise 桌面：宿主 route 已注册时优先直跳，避免 Mod 门面未就绪被守卫打回对话页 */
function preferHostSidebarRoute(router: Router, routeName: string): boolean {
  if (isAdminConsoleSpa()) return false
  const name = String(routeName || '')
    .replace(/^mod-/, '')
    .trim()
  if (!name.length || !router.hasRoute(name)) return false
  if (isDesktopShell() && isEnterpriseProductSkuBuild() && (INDUSTRY_DELIVERY_ERP_MENU_KEYS as readonly string[]).includes(name)) {
    return true
  }
  if (!isEnterpriseProductSkuBuild() || isPlatformShellModeEnabled()) return false
  return true
}

async function ensureModRoutesRegistered(router: Router, getModRoutes?: () => unknown[] | undefined) {
  const { registerAllModRoutesFromGlob, registerModRoutes } = await import('@/router/registerModRoutes')
  await registerAllModRoutesFromGlob(router)
  const routes = getModRoutes?.()
  if (routes?.length) {
    await registerModRoutes(router, routes as Parameters<typeof registerModRoutes>[1])
  }
}

/** Race mod-route registration against generation so a newer click can abort wait early. */
async function ensureModRoutesRegisteredUnlessStale(
  router: Router,
  getModRoutes: (() => unknown[] | undefined) | undefined,
  isStale: () => boolean,
): Promise<void> {
  if (isStale()) return
  const pending = ensureModRoutesRegistered(router, getModRoutes)
  let timer: ReturnType<typeof setInterval> | undefined
  try {
    await Promise.race([
      pending,
      new Promise<void>((resolve) => {
        timer = globalThis.setInterval(() => { if (isStale()) resolve() }, 40)
      }),
    ])
  } finally {
    globalThis.clearInterval(timer)
  }
}

async function pushSidebarRoute(
  router: Router,
  location: Parameters<Router['push']>[0],
  intentId: number,
  targetKey: string,
): Promise<boolean> {
  if (!isAppNavIntentCurrent(intentId)) return false
  const intent = {
    id: intentId,
    targetKey,
    source: 'sidebar',
    startedAt: Date.now(),
  }
  const matchName =
    typeof location === 'object' && location && 'name' in location
      ? String((location as { name?: unknown }).name ?? '')
      : null
  const matchPath =
    typeof location === 'string'
      ? location
      : typeof location === 'object' && location && 'path' in location
        ? String((location as { path?: unknown }).path ?? '')
        : null
  const result: AppNavOutcome = await pushWithAppNavIntent(router, location, intent, {
    isStale: () => !isAppNavIntentCurrent(intentId),
    match: { name: matchName, path: matchPath, key: targetKey },
  })
  if (shouldShowNavFailure(result.status)) {
    const err = result.error ?? new Error(result.message)
    throw err
  }
  // superseded: a newer user intent owns the UI; this call did not apply its own target.
  if (result.status === 'superseded') return false
  return result.status === 'arrived' || result.status === 'duplicate'
}

async function performSidebarNavigation(
  router: Router,
  viewKey: string,
  options: NavigateFromSidebarOptions,
  generation: number,
  intentId: number,
): Promise<boolean> {
  const isStale = () => generation !== sidebarNavGeneration || !isAppNavIntentCurrent(intentId)

  const modMenuItems = readModMenuItems(options.modMenuItems)
  const routeNameMap = options.routeNameMap || SIDEBAR_ROUTE_NAME_MAP

  const modItem = modMenuItems.find((m) => m.key === viewKey)
  const routeName = typeof viewKey === 'string' ? resolveNavRouteName(viewKey, modItem?.path) || viewKey : viewKey

  const nameCandidate = typeof routeName === 'string' ? routeName.replace(/^mod-/, '') : routeName

  if (typeof nameCandidate === 'string' && preferHostSidebarRoute(router, nameCandidate)) {
    return pushSidebarRoute(router, { name: nameCandidate }, intentId, viewKey)
  }

  if (modItem?.path) {
    if (router.resolve(modItem.path).matched.length === 0) {
      try {
        await ensureModRoutesRegisteredUnlessStale(router, options.getModRoutes, isStale)
      } catch (e) {
        console.warn('[sidebarNavigation] 补注册 Mod 路由失败:', e)
      }
    }
    if (isStale()) return false
    if (router.resolve(modItem.path).matched.length > 0) {
      return pushSidebarRoute(router, modItem.path, intentId, viewKey)
    }
    const legacy = resolveLegacyRouteFromModPath(router, modItem.path)
    if (legacy) return pushSidebarRoute(router, legacy, intentId, viewKey)
    const csHost = customerServiceHostPathFromModPath(modItem.path)
    if (csHost) return pushSidebarRoute(router, csHost, intentId, viewKey)
    console.warn('[sidebarNavigation] Mod 路由未注册，路径无效:', modItem.path)
  }

  if (typeof routeName === 'string') {
    const stripped = routeName.replace(/^mod-/, '')
    const modBusinessPath = resolveHostBusinessPageRedirect(stripped) || resolveHostBusinessPageRedirect(routeName)
    if (modBusinessPath) {
      if (router.resolve(modBusinessPath).matched.length === 0) {
        try {
          await ensureModRoutesRegisteredUnlessStale(router, options.getModRoutes, isStale)
        } catch (e) {
          console.warn('[sidebarNavigation] 补注册 Mod 路由失败:', e)
        }
      }
      if (isStale()) return false
      if (router.resolve(modBusinessPath).matched.length > 0) {
        return pushSidebarRoute(router, modBusinessPath, intentId, viewKey)
      }
      const legacy = resolveLegacyRouteFromModPath(router, modBusinessPath)
      if (legacy) return pushSidebarRoute(router, legacy, intentId, viewKey)
      const csHost = customerServiceHostPathFromModPath(modBusinessPath)
      if (csHost) return pushSidebarRoute(router, csHost, intentId, viewKey)
    }
  }

  if (typeof nameCandidate === 'string' && router.hasRoute(nameCandidate)) {
    return pushSidebarRoute(router, { name: nameCandidate }, intentId, viewKey)
  }
  if (typeof routeName === 'string' && router.hasRoute(routeName)) {
    return pushSidebarRoute(router, { name: routeName }, intentId, viewKey)
  }

  const routePath = Object.entries(routeNameMap).find(([, name]) => name === viewKey)?.[0]
  if (routePath) return pushSidebarRoute(router, routePath, intentId, viewKey)

  console.warn('[sidebarNavigation] 侧栏无对应路由:', viewKey)
  return false
}

async function drainSidebarNavigationQueue(router: Router): Promise<boolean> {
  let applied = false
  try {
    while (queuedSidebarViewKey) {
      // 合并同一事件循环内的连点，只保留最后一次侧栏目标
      await Promise.resolve()
      if (!queuedSidebarViewKey) break
      const key = queuedSidebarViewKey
      const opts = queuedSidebarOptions || {}
      const generation = sidebarNavGeneration
      const intentId = getAppNavIntentId()
      queuedSidebarViewKey = null
      queuedSidebarOptions = null
      try {
        applied = await performSidebarNavigation(router, key, opts, generation, intentId)
      } finally {
        // Only the still-current intent may clear; a newer click keeps its pending state.
        if (isAppNavIntentCurrent(intentId)) clearAppNavIntentIfCurrent(intentId)
      }
    }
  } finally {
    sidebarNavDrain = null
    if (queuedSidebarViewKey) sidebarNavDrain = drainSidebarNavigationQueue(router)
  }
  return applied
}

export function getQueuedSidebarViewKey(): string | null {
  return queuedSidebarViewKey
}

export function isSidebarNavigationPending(): boolean {
  return sidebarNavDrain != null || queuedSidebarViewKey != null
}

/**
 * 侧栏 / xcagi:switch-view 统一导航：单队列 drain + 合并连点 + Enterprise 宿主路由优先。
 * 新点击会抬升 generation，使仍在 await 的旧导航尽快判定 stale 并让出，不堵住快速连点。
 */
export function navigateFromSidebarKey(
  router: Router,
  viewKey: string,
  options: NavigateFromSidebarOptions & { source?: string } = {},
): Promise<boolean> {
  const normalized = String(viewKey || '').trim()
  if (!normalized) return Promise.resolve(false)

  queuedSidebarViewKey = normalized
  queuedSidebarOptions = options
  sidebarNavGeneration += 1
  beginAppNavIntent(normalized, options.source || 'sidebar')

  if (!sidebarNavDrain) {
    sidebarNavDrain = drainSidebarNavigationQueue(router)
  }
  return sidebarNavDrain
}

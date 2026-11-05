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
type SidebarNavigationRequest = {
  router: Router
  key: string
  options: NavigateFromSidebarOptions
  generation: number
  resolve: (applied: boolean) => void
  reject: (error: unknown) => void
}
let queuedSidebarNavigation: SidebarNavigationRequest | null = null
let activeSidebarNavigation: SidebarNavigationRequest | null = null

export function resetSidebarNavigationForTests(): void {
  queuedSidebarNavigation?.resolve(false)
  activeSidebarNavigation?.resolve(false)
  queuedSidebarNavigation = null
  activeSidebarNavigation = null
  sidebarNavGeneration = 0
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
  isStale: () => boolean,
  intentId: number,
  targetKey: string,
): Promise<boolean> {
  if (isStale() || !isAppNavIntentCurrent(intentId)) return false
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
    isStale: () => isStale() || !isAppNavIntentCurrent(intentId),
    match: { name: matchName, path: matchPath, key: targetKey },
  })
  // Soft router failures settle as false so coalesced callers keep independent
  // promises and MainLayout can mark a retryable fail without inheriting throws.
  if (result.status === 'aborted' || result.status === 'cancelled') return false
  if (shouldShowNavFailure(result.status)) {
    throw result.error ?? new Error(result.message)
  }
  if (result.status === 'superseded') return false
  return result.status === 'arrived' || result.status === 'duplicate'
}

async function performSidebarNavigation(
  router: Router,
  viewKey: string,
  options: NavigateFromSidebarOptions,
  generation: number,
  isCurrent: () => boolean,
  intentId: number,
): Promise<boolean> {
  const isStale = () => generation !== sidebarNavGeneration || !isCurrent() || !isAppNavIntentCurrent(intentId)

  const modMenuItems = readModMenuItems(options.modMenuItems)
  const routeNameMap = options.routeNameMap || SIDEBAR_ROUTE_NAME_MAP

  const modItem = modMenuItems.find((m) => m.key === viewKey)
  const routeName = typeof viewKey === 'string' ? resolveNavRouteName(viewKey, modItem?.path) || viewKey : viewKey

  const nameCandidate = typeof routeName === 'string' ? routeName.replace(/^mod-/, '') : routeName

  if (typeof nameCandidate === 'string' && preferHostSidebarRoute(router, nameCandidate)) {
    return pushSidebarRoute(router, { name: nameCandidate }, isStale, intentId, viewKey)
  }

  if (modItem?.path) {
    if (router.resolve(modItem.path).matched.length === 0) {
      try {
        await ensureModRoutesRegisteredUnlessStale(router, options.getModRoutes, isStale)
      } catch (e) {
        if (!isStale()) console.warn('[sidebarNavigation] 补注册 Mod 路由失败:', e)
      }
    }
    if (isStale()) return false
    if (router.resolve(modItem.path).matched.length > 0) {
      return pushSidebarRoute(router, modItem.path, isStale, intentId, viewKey)
    }
    const legacy = resolveLegacyRouteFromModPath(router, modItem.path)
    if (legacy) return pushSidebarRoute(router, legacy, isStale, intentId, viewKey)
    const csHost = customerServiceHostPathFromModPath(modItem.path)
    if (csHost) return pushSidebarRoute(router, csHost, isStale, intentId, viewKey)
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
          if (!isStale()) console.warn('[sidebarNavigation] 补注册 Mod 路由失败:', e)
        }
      }
      if (isStale()) return false
      if (router.resolve(modBusinessPath).matched.length > 0) {
        return pushSidebarRoute(router, modBusinessPath, isStale, intentId, viewKey)
      }
      const legacy = resolveLegacyRouteFromModPath(router, modBusinessPath)
      if (legacy) return pushSidebarRoute(router, legacy, isStale, intentId, viewKey)
      const csHost = customerServiceHostPathFromModPath(modBusinessPath)
      if (csHost) return pushSidebarRoute(router, csHost, isStale, intentId, viewKey)
    }
  }

  if (typeof nameCandidate === 'string' && router.hasRoute(nameCandidate)) {
    return pushSidebarRoute(router, { name: nameCandidate }, isStale, intentId, viewKey)
  }
  if (typeof routeName === 'string' && router.hasRoute(routeName)) {
    return pushSidebarRoute(router, { name: routeName }, isStale, intentId, viewKey)
  }

  const routePath = Object.entries(routeNameMap).find(([, name]) => name === viewKey)?.[0]
  if (routePath) return pushSidebarRoute(router, routePath, isStale, intentId, viewKey)

  console.warn('[sidebarNavigation] 侧栏无对应路由:', viewKey)
  return false
}

function drainSidebarNavigationQueue(): void {
  if (activeSidebarNavigation || !queuedSidebarNavigation) return
  const request = queuedSidebarNavigation
  queuedSidebarNavigation = null
  activeSidebarNavigation = request
  const intentId = getAppNavIntentId()
  void performSidebarNavigation(
    request.router,
    request.key,
    request.options,
    request.generation,
    () => activeSidebarNavigation === request,
    intentId,
  )
    .then(
      (applied) => finishSidebarNavigation(request, applied, undefined, false, intentId),
      (error) => finishSidebarNavigation(request, false, error, true, intentId),
    )
}

function finishSidebarNavigation(
  request: SidebarNavigationRequest,
  applied: boolean,
  error?: unknown,
  failed = false,
  intentId?: number,
): void {
  if (activeSidebarNavigation !== request) return
  activeSidebarNavigation = null
  if (intentId != null) clearAppNavIntentIfCurrent(intentId)
  if (failed) request.reject(error)
  else request.resolve(applied)
  if (queuedSidebarNavigation) queueMicrotask(drainSidebarNavigationQueue)
}

export function getQueuedSidebarViewKey(): string | null {
  return queuedSidebarNavigation?.key || null
}

export function isSidebarNavigationPending(): boolean {
  return activeSidebarNavigation != null || queuedSidebarNavigation != null
}

/**
 * 侧栏 / xcagi:switch-view 统一导航：单队列 drain + 合并连点 + Enterprise 宿主路由优先。
 * 新点击会抬升 generation，使仍在 await 的旧导航尽快判定 stale 并让出，不堵住快速连点。
 */
export function navigateFromSidebarKey(router: Router, viewKey: string, options: NavigateFromSidebarOptions = {}): Promise<boolean> {
  const normalized = String(viewKey || '').trim()
  if (!normalized) return Promise.resolve(false)

  sidebarNavGeneration += 1
  beginAppNavIntent(normalized, options.source || 'sidebar')
  const hadActiveNavigation = activeSidebarNavigation != null
  queuedSidebarNavigation?.resolve(false)
  activeSidebarNavigation?.resolve(false)
  activeSidebarNavigation = null
  const result = new Promise<boolean>((resolve, reject) => {
    queuedSidebarNavigation = { router, key: normalized, options, generation: sidebarNavGeneration, resolve, reject }
  })
  if (hadActiveNavigation) drainSidebarNavigationQueue()
  else queueMicrotask(drainSidebarNavigationQueue)
  return result
}

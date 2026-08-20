import type { Router } from 'vue-router'
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

async function performSidebarNavigation(
  router: Router,
  viewKey: string,
  options: NavigateFromSidebarOptions,
  generation: number,
): Promise<boolean> {
  const isStale = () => generation !== sidebarNavGeneration

  const modMenuItems = readModMenuItems(options.modMenuItems)
  const routeNameMap = options.routeNameMap || SIDEBAR_ROUTE_NAME_MAP

  const modItem = modMenuItems.find((m) => m.key === viewKey)
  const routeName = typeof viewKey === 'string' ? resolveNavRouteName(viewKey, modItem?.path) || viewKey : viewKey

  const nameCandidate = typeof routeName === 'string' ? routeName.replace(/^mod-/, '') : routeName

  if (typeof nameCandidate === 'string' && preferHostSidebarRoute(router, nameCandidate)) {
    if (isStale()) return false
    await router.push({ name: nameCandidate })
    return !isStale()
  }

  if (modItem?.path) {
    if (router.resolve(modItem.path).matched.length === 0) {
      try {
        await ensureModRoutesRegistered(router, options.getModRoutes)
      } catch (e) {
        console.warn('[sidebarNavigation] 补注册 Mod 路由失败:', e)
      }
    }
    if (isStale()) return false
    if (router.resolve(modItem.path).matched.length > 0) {
      await router.push(modItem.path)
      return !isStale()
    }
    const legacy = resolveLegacyRouteFromModPath(router, modItem.path)
    if (legacy) {
      await router.push(legacy)
      return !isStale()
    }
    const csHost = customerServiceHostPathFromModPath(modItem.path)
    if (csHost) {
      await router.push(csHost)
      return !isStale()
    }
    console.warn('[sidebarNavigation] Mod 路由未注册，路径无效:', modItem.path)
  }

  if (typeof routeName === 'string') {
    const stripped = routeName.replace(/^mod-/, '')
    const modBusinessPath = resolveHostBusinessPageRedirect(stripped) || resolveHostBusinessPageRedirect(routeName)
    if (modBusinessPath) {
      if (router.resolve(modBusinessPath).matched.length === 0) {
        try {
          await ensureModRoutesRegistered(router, options.getModRoutes)
        } catch (e) {
          console.warn('[sidebarNavigation] 补注册 Mod 路由失败:', e)
        }
      }
      if (isStale()) return false
      if (router.resolve(modBusinessPath).matched.length > 0) {
        await router.push(modBusinessPath)
        return !isStale()
      }
      const legacy = resolveLegacyRouteFromModPath(router, modBusinessPath)
      if (legacy) {
        await router.push(legacy)
        return !isStale()
      }
      const csHost = customerServiceHostPathFromModPath(modBusinessPath)
      if (csHost) {
        await router.push(csHost)
        return !isStale()
      }
    }
  }

  if (typeof nameCandidate === 'string' && router.hasRoute(nameCandidate)) {
    if (isStale()) return false
    await router.push({ name: nameCandidate })
    return !isStale()
  }
  if (typeof routeName === 'string' && router.hasRoute(routeName)) {
    if (isStale()) return false
    await router.push({ name: routeName })
    return !isStale()
  }

  const routePath = Object.entries(routeNameMap).find(([, name]) => name === viewKey)?.[0]
  if (routePath) {
    if (isStale()) return false
    await router.push(routePath)
    return !isStale()
  }

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
      queuedSidebarViewKey = null
      queuedSidebarOptions = null
      applied = await performSidebarNavigation(router, key, opts, generation)
    }
  } finally {
    sidebarNavDrain = null
  }
  return applied
}

/**
 * 侧栏 / xcagi:switch-view 统一导航：单队列 drain + 合并连点 + Enterprise 宿主路由优先。
 */
export function navigateFromSidebarKey(router: Router, viewKey: string, options: NavigateFromSidebarOptions = {}): Promise<boolean> {
  const normalized = String(viewKey || '').trim()
  if (!normalized) return Promise.resolve(false)

  queuedSidebarViewKey = normalized
  queuedSidebarOptions = options
  sidebarNavGeneration += 1

  if (!sidebarNavDrain) {
    sidebarNavDrain = drainSidebarNavigationQueue(router)
  }
  return sidebarNavDrain
}

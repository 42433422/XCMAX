import type { RouteRecordRaw } from 'vue-router'
import { isPlatformShellModeEnabled, INDUSTRY_DELIVERY_ROUTE_NAMES, SHELL_CORE_ROUTE_NAMES } from '@/constants/platformShellMode'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'

const SANDBOX_ALLOWED = new Set([
  'login',
  'login-help',
  'login-register',
  'login-forgot-account',
  'login-forgot-password',
  'chat',
  'workflow-employee-space',
  'workflow-employee-stitch-full',
  'mod-landing',
  'chat-debug',
  'tools',
])

function filterSandboxRoutes(routes: RouteRecordRaw[]): RouteRecordRaw[] {
  return routes.filter((route) => {
    if (!route.name) return false
    if (SANDBOX_ALLOWED.has(route.name as string)) return true
    return route.path === '/employee-workspace' || route.path === '/yuangong-stitch'
  })
}

function filterPlatformShellRoutes(routes: RouteRecordRaw[]): RouteRecordRaw[] {
  return routes.filter((route) => {
    if (!route.name) return false
    if (SHELL_CORE_ROUTE_NAMES.has(route.name as string)) return true
    if (INDUSTRY_DELIVERY_ROUTE_NAMES.has(route.name as string)) return true
    if (route.meta?.mod === true || route.meta?.hostAdmin === true) return true
    if (route.path === '/employee-workspace' || route.path === '/yuangong-stitch') return true
    return route.path?.startsWith('/mod/') === true
  })
}

export function resolveInitialRoutes(allRoutes: RouteRecordRaw[]): RouteRecordRaw[] {
  if (isAdminConsoleSpa()) return allRoutes
  if (new URLSearchParams(window.location.search).has('sandbox')) return filterSandboxRoutes(allRoutes)
  if (isPlatformShellModeEnabled()) return filterPlatformShellRoutes(allRoutes)
  return allRoutes
}

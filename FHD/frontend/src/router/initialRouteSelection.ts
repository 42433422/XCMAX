import type { RouteRecordRaw } from 'vue-router'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'

const SANDBOX_ALLOWED = new Set([
  'login',
  'login-help',
  'login-legal',
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

export function resolveInitialRoutes(allRoutes: RouteRecordRaw[]): RouteRecordRaw[] {
  if (isAdminConsoleSpa()) return allRoutes
  if (new URLSearchParams(window.location.search).has('sandbox')) return filterSandboxRoutes(allRoutes)
  return allRoutes
}

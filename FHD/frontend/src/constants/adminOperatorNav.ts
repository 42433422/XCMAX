/**
 * 企业端 SPA：运维菜单与路由在独立管理端（/admin，见 admin-console/）。
 * 管理员登录后由路由守卫跳转至 /admin。
 */
import type { CoreMenuCatalogItem } from '@/constants/coreMenuCatalog'

export const ADMIN_OPERATOR_MENU_ITEMS: CoreMenuCatalogItem[] = []
export const ADMIN_OPERATOR_AUX_MENU_ITEMS: CoreMenuCatalogItem[] = []
export const ADMIN_SIDEBAR_PINNED_TOP_KEYS: string[] = []

export const ADMIN_OPERATOR_VISIBLE_CORE_KEYS = new Set<string>()

export const ADMIN_OPERATOR_CORE_KEYS = ADMIN_OPERATOR_VISIBLE_CORE_KEYS

export const ADMIN_OPERATOR_HOME_ROUTE = 'chat'

export const ADMIN_OPERATOR_BRAND_TITLE = 'XCMAX'
export const ADMIN_OPERATOR_BRAND_SUBTITLE = ''

export function isAdminOperatorNavContext(_activeView: string, _isAdminAccount: boolean): boolean {
  return false
}

export const ADMIN_OPERATOR_ROUTE_NAMES = new Set([
  'login',
  'login-help',
  'login-forgot-account',
  'login-forgot-password',
  'lan-gate',
  'chat',
])

export const ADMIN_OPERATOR_HIDDEN_MOD_IDS = new Set<string>()
export const ADMIN_OPERATOR_ATTENDANCE_MOD_IDS = new Set<string>()
export const ADMIN_OPERATOR_ERP_MOD_MENU_ALLOWLIST = new Set<string>()
export const ADMIN_OPERATOR_HIDDEN_HOST_KEYS = new Set<string>()

export const ADMIN_OPERATOR_BLOCKED_ROUTE_NAMES = new Set<string>()

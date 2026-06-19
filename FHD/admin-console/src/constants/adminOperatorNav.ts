/**
 * 平台管理员 · XCMAX 服务器后台（与太阳鸟企业 ERP 壳分离）
 */

import type { CoreMenuCatalogItem } from '@/constants/coreMenuCatalog'

/** 运维顶栏（侧栏置顶，与 6/4 会话一致） */
export const ADMIN_OPERATOR_MENU_ITEMS: CoreMenuCatalogItem[] = [
  { key: 'xcmax-admin', name: '服务器后台总览', iconClass: 'fa-dashboard' },
  { key: 'automation-policy', name: '自动化方针', iconClass: 'fa-random' },
  { key: 'server-functions', name: '服务器功能模块', iconClass: 'fa-server' },
]

export const ADMIN_SIDEBAR_PINNED_TOP_KEYS = ADMIN_OPERATOR_MENU_ITEMS.map((m) => m.key)

/**
 * 管理端专用宿主菜单（不进企业端 CORE_MENU_ITEMS_TRAILING）。
 * 管理端 modsForUi=[]，Mod 侧栏不注入，须在此显式列出运维常用入口。
 */
export const ADMIN_OPERATOR_AUX_MENU_ITEMS: CoreMenuCatalogItem[] = [
  { key: 'im', name: '信息', iconClass: 'fa-envelope-o' },
  { key: 'internal-customer-service', name: '内部客服', iconClass: 'fa-headphones' },
  { key: 'data-sources', name: '数据来源', iconClass: 'fa-database' },
  { key: 'tools', name: '工具表', iconClass: 'fa-wrench' },
  { key: 'mod-store', name: '能力库', iconClass: 'fa-puzzle-piece' },
]

/** 管理员宿主 core/aux 可见 key（不含运维顶栏三项） */
export const ADMIN_OPERATOR_VISIBLE_CORE_KEYS = new Set([
  'chat',
  'ai-ecosystem',
  'employee-workflow',
  'workflow-employee-space',
  'workflow-visualization',
  'mod-store',
  'im',
  'tools',
  'data-sources',
  'chat-debug',
  'internal-customer-service',
  'mod-internal-customer-service',
  'desktop-runtime',
  'duty-roster-graph',
])

/** @deprecated 使用 ADMIN_OPERATOR_VISIBLE_CORE_KEYS */
export const ADMIN_OPERATOR_CORE_KEYS = ADMIN_OPERATOR_VISIBLE_CORE_KEYS

export const ADMIN_OPERATOR_HOME_ROUTE = 'xcmax-admin'

export const ADMIN_OPERATOR_BRAND_TITLE = 'XCMAX 服务器后台'
export const ADMIN_OPERATOR_BRAND_SUBTITLE = '平台运维 · 系统管理'

export function isAdminOperatorNavContext(
  activeView: string,
  isAdminAccount: boolean,
): boolean {
  if (isAdminAccount) return true
  const key = String(activeView || '').trim()
  if (ADMIN_OPERATOR_MENU_ITEMS.some((m) => m.key === key)) return true
  return Boolean(key && ADMIN_OPERATOR_VISIBLE_CORE_KEYS.has(key))
}

/** 管理员可访问的路由 name */
export const ADMIN_OPERATOR_ROUTE_NAMES = new Set([
  ...ADMIN_OPERATOR_MENU_ITEMS.map((m) => m.key),
  ...ADMIN_OPERATOR_VISIBLE_CORE_KEYS,
  'admin-entitlements',
  'settings',
  'login',
  'login-help',
  'login-forgot-account',
  'login-forgot-password',
  'lan-gate',
  'product-onboarding',
  'workflow-employee-stitch-full',
  'workflow-employee-load-remove',
  'brain',
  'wechat-contacts',
  'mod-landing',
  'attendance-industry-home',
  'attendance-industry-settings',
  'taiyangniao-pro-home',
  'taiyangniao-pro-settings',
])

export const ADMIN_OPERATOR_HIDDEN_MOD_IDS = new Set([
  'coating-industry',
  'sz-qsm-pro',
  'xcagi-workflow-visualization-bridge',
])

export const ADMIN_OPERATOR_ATTENDANCE_MOD_IDS = new Set(['attendance-industry', 'taiyangniao-pro'])

export const ADMIN_OPERATOR_ERP_MOD_MENU_ALLOWLIST = new Set(['mod-erp-data-sources'])

export const ADMIN_OPERATOR_HIDDEN_HOST_KEYS = new Set([
  'products',
  'materials',
  'materials-list',
  'traditional-mode',
  'orders',
  'orders-create',
  'shipment-records',
  'customers',
  'print',
  'approval-hub',
  'printer-list',
  'template-preview',
  'enterprise-customer-service',
])

export const ADMIN_OPERATOR_BLOCKED_ROUTE_NAMES = new Set([
  'products',
  'materials',
  'materials-list',
  'traditional-mode',
  'orders',
  'orders-create',
  'shipment-records',
  'customers',
  'print',
  'approval-hub',
  'approval-workspace',
  'approval-flow-management',
  'approval-rules',
  'inventory',
  'kitten-finance',
  'enterprise-customer-service',
  'printer-list',
  'template-preview',
])

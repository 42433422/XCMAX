import {
  readBuildEdition,
  hasInstalledAccountCustomMod,
} from '@/constants/genericModPack'
import { removeTenantScopedStorageItem } from '@/utils/tenantStorageScope'
import { XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY } from '@/utils/xcagiStorageKeys'

const INDUSTRY_PROFILE_MOD_IDS = new Set(['accessories-packaging-industry'])

function hasInstalledIndustryProfileMod(installedModIds: Iterable<string>): boolean {
  return Array.from(installedModIds).some((id) => INDUSTRY_PROFILE_MOD_IDS.has(String(id || '').trim()))
}

/**
 * 客户端只保留企业版完整路由。通用壳 / 精简壳不再裁菜单或路由。
 * `xcagi_platform_shell_mode` 启动时清成 0，避免旧配置把企业版设置页打空。
 */

export const LS_PLATFORM_SHELL_MODE = 'xcagi_platform_shell_mode'

export const LS_PLATFORM_SHELL_AUTO_GENERIC = 'xcagi_platform_shell_auto_generic'

export const LS_PLATFORM_SHELL_AUTO_MINIMAL = 'xcagi_platform_shell_auto_minimal'

/** 壳模式保留的侧栏 key（与 router name 对齐；含员工工作流分组及子项） */
export const SHELL_CORE_MENU_KEYS = new Set([
  'chat',
  'im',
  'ai-ecosystem',
  'persy-knowledge',
  'business-docking',
  'employee-workflow',
  'workflow-employee-space',
  'settings',
  'mod-store',
  'desktop-runtime',
  'login',
])

/** 壳模式允许注册的路由 name */
export const SHELL_CORE_ROUTE_NAMES = new Set([
  ...SHELL_CORE_MENU_KEYS,
  'task-workspace',
  'product-onboarding',
  'mod-landing',
  'workflow-employee-stitch-full',
  'lan-gate',
  'login',
  'login-help',
  'login-legal',
  'login-register',
  'login-forgot-account',
  'login-forgot-password',
  // AI 生态「生产员工」轻量页。
  'private-mod-delivery',
])

/** 账号定制 Mod 装齐后开放的宿主 ERP 侧栏（与 industry preset menuLabels 对齐） */
export const INDUSTRY_DELIVERY_ERP_MENU_KEYS = [
  'products',
  'customers',
  'orders',
  'shipment-records',
  'materials',
  'inventory',
  'data-sources',
  'traditional-mode',
  'print',
  'printer-list',
  'template-preview',
  'tools',
  'approval-hub',
] as const

export const INDUSTRY_DELIVERY_ROUTE_NAMES = new Set<string>([
  ...INDUSTRY_DELIVERY_ERP_MENU_KEYS,
  'inventory',
  'printer-list',
  'template-preview',
  'data-sources',
  'kitten-finance',
  'workflow-visualization',
  'workflow-employee-space',
  'other-tools',
  'attendance-industry-home',
  'attendance-industry-settings',
  'qsm-pro-home',
  'sz-qsm-pro-home',
])

/**
 * 平台壳模式下是否放开行业业务侧栏（主导航长出行业菜单）。
 * 触发任一：
 * - 引导第三步「补基础线」已确认（host_pack_acknowledged）—— 用户走完引导即长出；
 * - 已安装账号定制 Mod（奇士美等 entitlement 直发场景）；
 * - 已安装行业画像包（太阳鸟现使用饰品包装行业包 + 统一考勤能力）。
 * 未走引导且无定制时保持初始化的 5 项核心壳菜单。
 */
export function shouldExposeIndustrySidebar(installedModIds: Iterable<string>, hostPackAcknowledged = false): boolean {
  if (hostPackAcknowledged) return true
  const ids = Array.from(installedModIds)
  return hasInstalledAccountCustomMod(ids) || hasInstalledIndustryProfileMod(ids)
}

export function resolvePlatformShellMenuKeys(installedModIds: Iterable<string>, hostPackAcknowledged = false): Set<string> {
  const keys = new Set(SHELL_CORE_MENU_KEYS)
  if (!shouldExposeIndustrySidebar(installedModIds, hostPackAcknowledged)) return keys
  for (const k of INDUSTRY_DELIVERY_ERP_MENU_KEYS) keys.add(k)
  return keys
}

export function isIndustryDeliveryRouteName(routeName: string, installedModIds: Iterable<string>, hostPackAcknowledged = false): boolean {
  const name = String(routeName || '').trim()
  if (!name || !INDUSTRY_DELIVERY_ROUTE_NAMES.has(name)) return false
  return shouldExposeIndustrySidebar(installedModIds, hostPackAcknowledged)
}

export function readPlatformShellModeFromStorage(): boolean {
  if (typeof localStorage === 'undefined') return false
  try {
    return localStorage.getItem(LS_PLATFORM_SHELL_MODE) === '1'
  } catch {
    return false
  }
}

export function isMinimalEditionBuild(): boolean {
  return readBuildEdition() === 'minimal'
}

export function isGenericEditionBuild(): boolean {
  if (readBuildEdition() === 'generic') return true
  const def = String(import.meta.env.VITE_XCAGI_DEFAULT_PLATFORM_SHELL || '')
    .trim()
    .toLowerCase()
  return def === '1' || def === 'true' || def === 'yes'
}

export function isShellEditionBuild(): boolean {
  return false
}

function clearPlatformShellPreference(): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '0')
    localStorage.removeItem(LS_PLATFORM_SHELL_AUTO_MINIMAL)
    localStorage.removeItem(LS_PLATFORM_SHELL_AUTO_GENERIC)
  } catch {
    /* ignore */
  }
}

/** 须在 import router 之前调用。清掉旧通用壳标记，不再按 edition 写回 1。 */
export function bootstrapMinimalEditionDefaults(): void {
  clearPlatformShellPreference()
}

export function bootstrapGenericEditionDefaults(): void {
  clearPlatformShellPreference()
}

export function bootstrapEditionDefaults(): void {
  clearPlatformShellPreference()
}

export function isEnterpriseProductSkuBuild(): boolean {
  const raw = String(import.meta.env.VITE_XCAGI_PRODUCT_SKU || '')
    .trim()
    .toLowerCase()
  return raw === 'enterprise'
}

/** 企业版默认完整侧栏与路由，不进入通用平台壳 */
export function bootstrapEnterpriseShellDefaults(): void {
  if (!isEnterpriseProductSkuBuild()) return
  clearPlatformShellPreference()
}

/** 管理端 SPA 须保留运维路由，禁用平台壳与 Mod 门面重定向 */
export function bootstrapAdminConsoleShellDefaults(): void {
  const raw = String(import.meta.env.VITE_XCMAX_ADMIN_CONSOLE || '').trim()
  if (raw !== '1') return
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '0')
    removeTenantScopedStorageItem(XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY)
    localStorage.setItem('xcagi_lan_mod_facade_enabled', '0')
    localStorage.setItem('xcagi_planner_mod_facade_enabled', '0')
    localStorage.setItem('xcagi_erp_domain_mod_facade_enabled', '0')
    localStorage.setItem('xcagi_workflow_viz_mod_pages_enabled', '0')
  } catch {
    /* ignore */
  }
}

export function isPlatformShellModeEnabled(): boolean {
  return false
}

/** Mod 列表加载后不再自动打开通用壳。 */
export function applyMinimalPackPlatformShell(_installedModIds: string[]): void {
  clearPlatformShellPreference()
}

export function applyGenericPackPlatformShell(_installedModIds: string[]): void {
  clearPlatformShellPreference()
}

export function applyEditionPackPlatformShell(_installedModIds: string[]): void {
  clearPlatformShellPreference()
}

export function setPlatformShellModeEnabled(_on: boolean): void {
  clearPlatformShellPreference()
}

export function isHostBusinessMenuKey(key: string): boolean {
  return !SHELL_CORE_MENU_KEYS.has(key)
}

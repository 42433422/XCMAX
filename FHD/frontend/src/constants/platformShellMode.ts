import {
  readBuildEdition,
  shouldAutoEnableEditionPlatformShell,
  shouldAutoEnableMinimalPlatformShell,
  shouldAutoEnablePlatformShell,
  hasInstalledAccountCustomMod,
} from '@/constants/genericModPack'
import { removeTenantScopedStorageItem } from '@/utils/tenantStorageScope'
import { XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY } from '@/utils/xcagiStorageKeys'

/**
 * 通用化宿主壳模式（里程碑 A/D）：默认只展示壳菜单 + Mod 入口，隐藏内置 ERP 业务页。
 *
 * 启用方式（任一）：
 * - 构建环境变量 VITE_XCAGI_PLATFORM_SHELL=1
 * - URL 参数 ?shell=1
 * - localStorage xcagi_platform_shell_mode=1
 * - 构建 VITE_XCAGI_DEFAULT_PLATFORM_SHELL=1（通用发行版默认壳）
 * - 安装通用 Mod 包后自动开启（见 genericModPack.ts）
 */

export const LS_PLATFORM_SHELL_MODE = 'xcagi_platform_shell_mode'

export const LS_PLATFORM_SHELL_AUTO_GENERIC = 'xcagi_platform_shell_auto_generic'

export const LS_PLATFORM_SHELL_AUTO_MINIMAL = 'xcagi_platform_shell_auto_minimal'

/** 壳模式保留的侧栏 key（与 router name 对齐；含员工工作流分组及子项） */
export const SHELL_CORE_MENU_KEYS = new Set([
  'chat',
  'im',
  'ai-ecosystem',
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
  'product-onboarding',
  'mod-landing',
  'workflow-employee-stitch-full',
  'lan-gate',
  'login',
  'login-help',
  'login-register',
  'login-forgot-account',
  'login-forgot-password',
])

/** 账号定制 Mod 装齐后开放的宿主 ERP 侧栏（与 industry preset menuLabels 对齐） */
export const INDUSTRY_DELIVERY_ERP_MENU_KEYS = [
  'products',
  'customers',
  'orders',
  'shipment-records',
  'materials',
  'data-sources',
  'traditional-mode',
  'print',
  'printer-list',
  'template-preview',
  'tools',
  'approval-hub',
  'enterprise-customer-service',
  'internal-customer-service',
  'wechat-contacts',
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
  'taiyangniao-pro-home',
  'qsm-pro-home',
  'sz-qsm-pro-home',
])

/**
 * 平台壳模式下是否放开行业业务侧栏（主导航长出行业菜单）。
 * 触发任一：
 * - 引导第三步「补基础线」已确认（host_pack_acknowledged）—— 用户走完引导即长出；
 * - 已安装账号定制 Mod（太阳鸟/奇士美等 entitlement 直发场景）。
 * 未走引导且无定制时保持初始化的 4 项壳菜单。
 */
export function shouldExposeIndustrySidebar(
  installedModIds: Iterable<string>,
  hostPackAcknowledged = false,
): boolean {
  if (hostPackAcknowledged) return true
  return hasInstalledAccountCustomMod(installedModIds)
}

export function resolvePlatformShellMenuKeys(
  installedModIds: Iterable<string>,
  hostPackAcknowledged = false,
): Set<string> {
  const keys = new Set(SHELL_CORE_MENU_KEYS)
  if (!shouldExposeIndustrySidebar(installedModIds, hostPackAcknowledged)) return keys
  for (const k of INDUSTRY_DELIVERY_ERP_MENU_KEYS) keys.add(k)
  return keys
}

export function isIndustryDeliveryRouteName(
  routeName: string,
  installedModIds: Iterable<string>,
  hostPackAcknowledged = false,
): boolean {
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
  const def = String(import.meta.env.VITE_XCAGI_DEFAULT_PLATFORM_SHELL || '').trim().toLowerCase()
  return def === '1' || def === 'true' || def === 'yes'
}

export function isShellEditionBuild(): boolean {
  return isMinimalEditionBuild() || isGenericEditionBuild()
}

/** @deprecated 使用 isGenericEditionBuild */
function isDefaultPlatformShellBuild(): boolean {
  return isGenericEditionBuild()
}

/**
 * 须在 import router 之前调用（里程碑 I）：通用发行版构建默认写入壳模式偏好。
 */
export function bootstrapMinimalEditionDefaults(): void {
  if (!isMinimalEditionBuild()) return
  if (typeof localStorage === 'undefined') return
  try {
    if (localStorage.getItem(LS_PLATFORM_SHELL_MODE) === '0') return
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    localStorage.setItem(LS_PLATFORM_SHELL_AUTO_MINIMAL, 'minimal_edition_build')
  } catch {
    /* ignore */
  }
}

export function bootstrapGenericEditionDefaults(): void {
  if (!isGenericEditionBuild() || isMinimalEditionBuild()) return
  if (typeof localStorage === 'undefined') return
  try {
    if (localStorage.getItem(LS_PLATFORM_SHELL_MODE) === '0') return
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    localStorage.setItem(LS_PLATFORM_SHELL_AUTO_GENERIC, 'generic_edition_build')
  } catch {
    /* ignore */
  }
}

/** 须在 import router 之前调用（里程碑 Q/I） */
export function bootstrapEditionDefaults(): void {
  bootstrapMinimalEditionDefaults()
  bootstrapGenericEditionDefaults()
}

export function isEnterpriseProductSkuBuild(): boolean {
  const raw = String(import.meta.env.VITE_XCAGI_PRODUCT_SKU || '').trim().toLowerCase()
  return raw === 'enterprise'
}

/** 企业版默认完整侧栏与路由，不进入通用平台壳 */
export function bootstrapEnterpriseShellDefaults(): void {
  if (!isEnterpriseProductSkuBuild()) return
  if (isShellEditionBuild()) return
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '0')
  } catch {
    /* ignore */
  }
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
  if (isEnterpriseProductSkuBuild() && !isShellEditionBuild()) return false
  if (typeof window !== 'undefined') {
    if (new URLSearchParams(window.location.search).has('shell')) return true
    if (new URLSearchParams(window.location.search).has('full')) return false
  }
  if (typeof localStorage !== 'undefined') {
    try {
      const stored = localStorage.getItem(LS_PLATFORM_SHELL_MODE)
      if (stored === '0') return false
      if (stored === '1') return true
    } catch {
      /* ignore */
    }
  }
  const env = String(import.meta.env.VITE_XCAGI_PLATFORM_SHELL || '').trim().toLowerCase()
  if (env === '1' || env === 'true' || env === 'yes') return true
  if (isShellEditionBuild()) return true
  return false
}

/** Mod 列表加载后：minimal 发行包自动壳 */
export function applyMinimalPackPlatformShell(installedModIds: string[]): void {
  if (!shouldAutoEnableMinimalPlatformShell(installedModIds)) return
  if (typeof localStorage === 'undefined') return
  try {
    if (localStorage.getItem(LS_PLATFORM_SHELL_MODE) === '0') return
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    localStorage.setItem(LS_PLATFORM_SHELL_AUTO_MINIMAL, '1')
  } catch {
    /* ignore */
  }
}

/** Mod 列表加载后：完整 generic 发行包自动壳 */
export function applyGenericPackPlatformShell(installedModIds: string[]): void {
  if (!shouldAutoEnablePlatformShell(installedModIds)) return
  if (typeof localStorage === 'undefined') return
  try {
    if (localStorage.getItem(LS_PLATFORM_SHELL_MODE) === '0') return
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    localStorage.setItem(LS_PLATFORM_SHELL_AUTO_GENERIC, '1')
  } catch {
    /* ignore */
  }
}

/** 按构建 edition 或已安装 Mod 集自动开壳 */
export function applyEditionPackPlatformShell(installedModIds: string[]): void {
  if (isEnterpriseProductSkuBuild()) return
  const edition = readBuildEdition()
  if (edition === 'minimal') {
    applyMinimalPackPlatformShell(installedModIds)
    return
  }
  if (edition === 'generic') {
    applyGenericPackPlatformShell(installedModIds)
    return
  }
  if (shouldAutoEnableMinimalPlatformShell(installedModIds)) {
    applyMinimalPackPlatformShell(installedModIds)
    return
  }
  applyGenericPackPlatformShell(installedModIds)
}

export function setPlatformShellModeEnabled(on: boolean): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, on ? '1' : '0')
  } catch {
    /* ignore */
  }
}

export function isHostBusinessMenuKey(key: string): boolean {
  return !SHELL_CORE_MENU_KEYS.has(key)
}

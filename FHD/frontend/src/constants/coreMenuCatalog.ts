/** 宿主侧栏菜单结构（与 router / MainLayout 对齐） */

export type CoreMenuCatalogItem = {
  key: string
  name: string
  iconClass: string
  children?: CoreMenuCatalogItem[]
}

/** 侧栏默认置顶项（行业 Mod 场景下仍保持在业务菜单之上） */
export const PRIMARY_CHAT_MENU_KEY = 'chat'

export function pinMenuKeyFirst<T extends { key: string }>(
  items: T[],
  key: string = PRIMARY_CHAT_MENU_KEY,
): T[] {
  const hit = items.find((i) => String(i.key) === key)
  if (!hit) return items
  return [hit, ...items.filter((i) => String(i.key) !== key)]
}

export const EMPLOYEE_WORKFLOW_MENU_CHILDREN: CoreMenuCatalogItem[] = [
  { key: 'workflow-employee-space', name: '员工空间', iconClass: 'fa-th-large' },
  { key: 'workflow-visualization', name: '流程全景', iconClass: 'fa-share-alt' },
]

/** 管理端「员工工作台」额外子项（企业端不可见） */
export const ADMIN_EMPLOYEE_WORKFLOW_MENU_CHILDREN: CoreMenuCatalogItem[] = [
  { key: 'duty-roster-graph', name: '编制图谱', iconClass: 'fa-sitemap' },
]

/** 侧栏分组：员工工作台 */
export const EMPLOYEE_WORKFLOW_MENU_ITEM: CoreMenuCatalogItem = {
  key: 'employee-workflow',
  name: '员工工作台',
  iconClass: 'fa-users',
  children: EMPLOYEE_WORKFLOW_MENU_CHILDREN,
}

export const CORE_MENU_ITEMS_BASE: CoreMenuCatalogItem[] = [
  { key: PRIMARY_CHAT_MENU_KEY, name: '智能对话', iconClass: 'fa-comments-o' },
  { key: 'im', name: '消息', iconClass: 'fa-envelope-o' },
  { key: 'ai-ecosystem', name: '智能生态', iconClass: 'fa-sitemap' },
  EMPLOYEE_WORKFLOW_MENU_ITEM,
]

/**
 * 引导第三步「补基础线」完成后，平台壳模式注入主导航的行业业务核心项。
 * label 由行业 preset（INDUSTRY_MENU_LABELS）与账号定制 Mod 的 menu_overrides 覆盖：
 * 考勤 → 人员管理/部门管理…；涂料 → 产品管理/客户管理…；通用 → 业务对象/组织管理…
 * key 与宿主 router name 一致，去重时占用对应宿主槽位（抑制 erp-domain-bridge 的同名 mod 入口）。
 */
export const INDUSTRY_DELIVERY_CORE_ITEMS: CoreMenuCatalogItem[] = [
  { key: 'products', name: '业务对象', iconClass: 'fa-cubes' },
  { key: 'customers', name: '组织管理', iconClass: 'fa-users' },
  { key: 'orders', name: '业务单据', iconClass: 'fa-file-text-o' },
  { key: 'shipment-records', name: '业务记录', iconClass: 'fa-industry' },
  { key: 'materials', name: '资源库', iconClass: 'fa-archive' },
  { key: 'print', name: '模板与打印', iconClass: 'fa-print' },
]

export const SETTINGS_MENU_ITEM: CoreMenuCatalogItem = {
  key: 'settings',
  name: '系统设置',
  iconClass: 'fa-cog',
}

export const CORE_MENU_ITEMS_TRAILING: CoreMenuCatalogItem[] = []

export const ADMIN_MENU_ITEM: CoreMenuCatalogItem = {
  key: 'admin-entitlements',
  name: '用户 Mod 管理',
  iconClass: 'fa-shield',
}

export const CORE_NAV_KEYS = [
  ...flattenNavKeys(CORE_MENU_ITEMS_BASE),
  ...CORE_MENU_ITEMS_TRAILING.map((m) => m.key),
  SETTINGS_MENU_ITEM.key,
]

export const SANDBOX_MENU_KEYS = new Set([
  'chat',
  'ai-ecosystem',
  'employee-workflow',
  'workflow-employee-space',
])

export function flattenNavKeys(items: Array<{ key: string; children?: Array<{ key: string }> }>): string[] {
  const out: string[] = []
  for (const item of items) {
    out.push(item.key)
    if (item.children?.length) {
      for (const child of item.children) {
        out.push(child.key)
      }
    }
  }
  return out
}

export function sidebarLayoutSeedKeys(): string[] {
  const keys = [
    ...CORE_MENU_ITEMS_BASE.map((m) => m.key),
    ...CORE_MENU_ITEMS_TRAILING.map((m) => m.key),
  ]
  return pinMenuKeyFirst(
    keys.map((key) => ({ key })),
    PRIMARY_CHAT_MENU_KEY,
  ).map((row) => row.key)
}

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

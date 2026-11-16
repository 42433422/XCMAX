import catalog from '../../../config/core_navigation.json'

/** 宿主侧栏菜单结构（与 router / MainLayout 对齐） */

export type CoreMenuCatalogItem = {
  key: string
  name: string
  iconClass: string
  /** 侧栏 hover 提示的一句话说明，帮用户分清「智能对话/信息」等相似入口。可选，缺省仅显示 name。 */
  description?: string
  children?: CoreMenuCatalogItem[]
}

/** 侧栏默认置顶项（行业 Mod 场景下仍保持在业务菜单之上） */
export const PRIMARY_CHAT_MENU_KEY = 'chat'

export function pinMenuKeyFirst<T extends { key: string }>(items: T[], key: string = PRIMARY_CHAT_MENU_KEY): T[] {
  const hit = items.find((i) => String(i.key) === key)
  if (!hit) return items
  return [hit, ...items.filter((i) => String(i.key) !== key)]
}

// Shared with the mobile navigation endpoint; role/Mod filtering stays in its owning policy.
export const EMPLOYEE_WORKFLOW_MENU_ITEM: CoreMenuCatalogItem = catalog.core.find(item => item.key === 'employee-workflow')!
export const EMPLOYEE_WORKFLOW_MENU_CHILDREN: CoreMenuCatalogItem[] = EMPLOYEE_WORKFLOW_MENU_ITEM.children || []
export const ADMIN_EMPLOYEE_WORKFLOW_MENU_CHILDREN: CoreMenuCatalogItem[] = catalog.admin_workflow_children
export const CORE_MENU_ITEMS_BASE: CoreMenuCatalogItem[] = catalog.core
export const INDUSTRY_DELIVERY_CORE_ITEMS: CoreMenuCatalogItem[] = catalog.industry
export const SETTINGS_MENU_ITEM: CoreMenuCatalogItem = catalog.settings
export const CORE_MENU_ITEMS_TRAILING: CoreMenuCatalogItem[] = []
export const ADMIN_MENU_ITEM: CoreMenuCatalogItem = catalog.admin

export const CORE_NAV_KEYS = [
  ...flattenNavKeys(CORE_MENU_ITEMS_BASE),
  ...CORE_MENU_ITEMS_TRAILING.map((m) => m.key),
  SETTINGS_MENU_ITEM.key,
]

export const SANDBOX_MENU_KEYS = new Set(['chat', 'ai-ecosystem', 'employee-workflow', 'workflow-employee-space'])

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
  const keys = [...CORE_MENU_ITEMS_BASE.map((m) => m.key), ...CORE_MENU_ITEMS_TRAILING.map((m) => m.key)]
  return pinMenuKeyFirst(
    keys.map((key) => ({ key })),
    PRIMARY_CHAT_MENU_KEY,
  ).map((row) => row.key)
}

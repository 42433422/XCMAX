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

export const CORE_MENU_ITEMS_BASE: CoreMenuCatalogItem[] = [
  { key: PRIMARY_CHAT_MENU_KEY, name: '智能对话', iconClass: 'fa-comments-o' },
  { key: 'ai-ecosystem', name: '智能生态', iconClass: 'fa-sitemap' },
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
  ...CORE_MENU_ITEMS_BASE.map((m) => m.key),
  ...CORE_MENU_ITEMS_TRAILING.map((m) => m.key),
  SETTINGS_MENU_ITEM.key,
]

export const SANDBOX_MENU_KEYS = new Set([
  'chat',
  'ai-ecosystem',
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

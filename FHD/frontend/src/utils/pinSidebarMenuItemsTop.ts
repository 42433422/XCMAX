/** 始终固定在侧栏主菜单顶部的宿主项（优先于 Mod 前置与用户拖拽排序） */
import { ADMIN_SIDEBAR_PINNED_TOP_KEYS } from '@/constants/adminOperatorNav'
import { MOD_MENU_ID_TO_HOST_NAV_KEY, normalizeModSidebarNavKey } from '@/constants/genericModPack'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'

export const SIDEBAR_PINNED_TOP_KEYS = ['chat'] as const

export function pinSidebarMenuItemsTop<T extends { key: string }>(items: T[]): T[] {
  if (!items.length) return items
  const pinKeys = isAdminConsoleSpa() ? [...ADMIN_SIDEBAR_PINNED_TOP_KEYS] : [...SIDEBAR_PINNED_TOP_KEYS]
  const pinSet = new Set<string>(pinKeys)
  const canonicalKey = (row: T): string => {
    const key = normalizeModSidebarNavKey(row.key)
    return MOD_MENU_ID_TO_HOST_NAV_KEY[key] || key
  }
  const pinned: T[] = []
  for (const key of pinKeys) {
    pinned.push(...items.filter((row) => canonicalKey(row) === key))
  }
  const rest = items.filter((row) => !pinSet.has(canonicalKey(row)))
  return [...pinned, ...rest]
}
